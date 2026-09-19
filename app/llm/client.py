"""b-api client (PLAN.md 7): OpenAI-compatible chat completions behind the ``X-API-KEY`` header.

Measured against ``b-api.staging.openeduhub.net`` on 2026-09-17: the path is
``/api/v1/llm/{provider}/chat/completions``; the GPT-5 and o-series models take
``max_completion_tokens``, ``reasoning_effort`` and ``verbosity`` and reject ``temperature``; classic
models take ``max_tokens`` and ``temperature``; Qwen3 models need ``chat_template_kwargs``
``{"enable_thinking": false}``. ``/models`` lists ``status`` and ``demand`` only for academiccloud.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.llm.budget import estimate_tokens

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 502, 503, 504})
HIGH_DEMAND = 3  # academiccloud reported demand 0 to 2 in normal operation (2026-09-17)
MODEL_CHECK_TIMEOUT_S = 10.0  # the model list is a probe (start-up, health): one short attempt, no retries
TRIP_TIMEOUT_S = 30.0  # a call cut short by the request deadline is no outage; half a minute of silence is
BREAKER_S = 60.0  # after a connection failure or a timeout, calls fail fast instead of queueing on the next timeout
SUSPENDED_MESSAGE = "b-api nach Verbindungsfehlern vorübergehend ausgesetzt"
_KEY_RE = re.compile(r"^[!-~]+$")  # printable ASCII without spaces; anything else breaks the header
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")
# Reasoning models count their thinking in max_completion_tokens; gpt-5.6-luna (reasoning_effort=low) used a
# block's whole limit of 555 tokens for it and answered with nothing (finish_reason=length, 2026-09-19)
REASONING_ALLOWANCE = 1000

Message = Mapping[str, str]


class LlmError(RuntimeError):
    """The b-api did not deliver a usable answer; ``status`` is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    finish_reason: str


@dataclass(frozen=True)
class ModelInfo:
    id: str
    status: str | None
    demand: int | None


@dataclass(frozen=True)
class ModelCheck:
    """Result of comparing the configured model with ``/models``; ``ok`` means the LLM may be used."""

    ok: bool
    model: str
    found: bool
    status: str | None
    demand: int | None
    message: str


def is_reasoning_model(model: str) -> bool:
    """GPT-5 and o-series models: completion-token limit, reasoning effort, verbosity, no temperature."""
    return model.lower().startswith(_REASONING_PREFIXES)


def needs_thinking_off(model: str) -> bool:
    return "qwen3" in model.lower()


class BApiClient:
    """Synchronous client with a concurrency semaphore and exponential backoff on 429/502/503/504."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        provider: str,
        model: str,
        timeout_s: float = 120.0,
        max_concurrency: int = 4,
        attempts: int = 3,
        backoff_s: float = 1.5,
        reasoning_effort: str = "low",
        verbosity: str = "low",
        temperature: float = 0.2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        api_key = api_key.strip()  # secret files usually end with a newline
        if not api_key:
            raise ValueError("b-api key is empty (B_API_KEY)")
        if not _KEY_RE.match(api_key):  # never echo the value
            raise ValueError("B_API_KEY contains whitespace or non-printable characters")
        self._key = api_key
        self._clock = clock
        self._open_until = 0.0
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.model = model
        self.timeout_s = timeout_s
        self.attempts = max(1, attempts)
        self.backoff_s = backoff_s
        self.reasoning_effort = reasoning_effort
        self.verbosity = verbosity
        self.temperature = temperature
        self._sleep = sleep
        self._semaphore = threading.BoundedSemaphore(max(1, max_concurrency))
        self._client = httpx.Client(
            headers={"X-API-KEY": api_key, "Accept": "application/json"}, timeout=timeout_s, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    @property
    def suspended(self) -> bool:
        """True while the circuit breaker is open after a connection failure or a timeout."""
        return self._clock() < self._open_until

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/api/v1/llm/{self.provider}/chat/completions"

    @property
    def models_url(self) -> str:
        return f"{self.base_url}/api/v1/llm/{self.provider}/models"

    def chat(
        self, messages: Sequence[Message], *, max_output_tokens: int, timeout_s: float | None = None
    ) -> ChatResult:
        """One chat completion; raises ``LlmError`` when the API fails or answers in an unexpected format.

        ``timeout_s`` shortens the configured timeout, e.g. to what is left of the request deadline.
        """
        body = self._body(messages, max_output_tokens)
        data = self._request("POST", self.chat_url, json_body=body, timeout_s=timeout_s)
        return _parse_completion(data, self.model, "".join(str(m.get("content", "")) for m in messages))

    def models(self) -> list[ModelInfo]:
        data = self._request("GET", self.models_url, attempts=1, timeout_s=MODEL_CHECK_TIMEOUT_S)
        entries = data.get("data") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise LlmError("/models answered without a model list")
        infos: list[ModelInfo] = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            demand = entry.get("demand")
            infos.append(
                ModelInfo(
                    id=str(entry["id"]),
                    status=str(entry["status"]) if entry.get("status") is not None else None,
                    demand=int(demand) if isinstance(demand, int | float) else None,
                )
            )
        return infos

    def check_model(self) -> ModelCheck:
        """Compare the configured model with ``/models``; never raises, the caller decides what to do."""
        try:
            infos = self.models()
        except LlmError as exc:
            return ModelCheck(False, self.model, False, None, None, f"b-api nicht erreichbar: {exc}")
        info = next((m for m in infos if m.id == self.model), None)
        if info is None:
            message = f"Modell {self.model!r} steht nicht in /models des Providers {self.provider}"
            return ModelCheck(False, self.model, False, None, None, message)
        if info.status is not None and info.status != "ready":
            return ModelCheck(
                False, self.model, True, info.status, info.demand, f"Modell {self.model} hat status {info.status}"
            )
        if info.demand is not None and info.demand >= HIGH_DEMAND:
            message = f"Modell {self.model} ist stark ausgelastet (demand {info.demand})"
            return ModelCheck(False, self.model, True, info.status, info.demand, message)
        return ModelCheck(True, self.model, True, info.status, info.demand, f"Modell {self.model} verfügbar")

    def completion_limit(self, answer_tokens: int) -> int:
        """The API's output limit for an answer of ``answer_tokens``: reasoning models also spend it on thinking."""
        return answer_tokens + REASONING_ALLOWANCE if is_reasoning_model(self.model) else answer_tokens

    def _body(self, messages: Sequence[Message], max_output_tokens: int) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": [dict(m) for m in messages]}
        if is_reasoning_model(self.model):
            body["max_completion_tokens"] = max_output_tokens
            body["reasoning_effort"] = self.reasoning_effort
            body["verbosity"] = self.verbosity
        else:
            body["max_tokens"] = max_output_tokens
            body["temperature"] = self.temperature
            if needs_thinking_off(self.model):
                body["chat_template_kwargs"] = {"enable_thinking": False}
        return body

    def _request(
        self,
        method: str,
        url: str,
        json_body: Mapping[str, Any] | None = None,
        *,
        attempts: int | None = None,
        timeout_s: float | None = None,
    ) -> Any:
        attempts = attempts or self.attempts
        limit = timeout_s if timeout_s is not None else self.timeout_s
        if self.suspended:
            raise LlmError(SUSPENDED_MESSAGE)
        last_error = ""
        status: int | None = None
        for attempt in range(attempts):
            try:
                response = self._send(method, url, json_body, limit)
            except httpx.TimeoutException as exc:
                # A request that timed out once will not answer in time on a retry within a synchronous request.
                if limit >= min(self.timeout_s, TRIP_TIMEOUT_S):
                    self._trip()
                raise LlmError(f"b-api antwortete nicht rechtzeitig ({type(exc).__name__})") from exc
            except httpx.HTTPError as exc:
                # httpx quotes illegal header values (the key) in its messages: redact before the text travels on.
                last_error, status = self._redact(f"{type(exc).__name__}: {exc}"), None
            else:
                status = response.status_code
                if status == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise LlmError("b-api antwortete ohne gültiges JSON", status) from exc
                if status not in RETRY_STATUSES:
                    # The upstream body stays in the log: messages reach /health, the audit and the frontmatter.
                    log.warning("b-api answered HTTP %s: %s", status, self._redact(response.text[:200]))
                    raise LlmError(f"b-api antwortete HTTP {status}", status)
                last_error = f"HTTP {status}"
            if attempt + 1 < attempts:
                self._sleep(self.backoff_s * 2**attempt)
        if status is None:
            self._trip()
        raise LlmError(f"b-api nach {attempts} Versuchen nicht erreichbar ({last_error})", status)

    def _send(self, method: str, url: str, json_body: Mapping[str, Any] | None, limit: float) -> httpx.Response:
        """One HTTP attempt; waiting for a free call slot counts against ``limit`` like the request itself."""
        began = time.monotonic()
        if not self._semaphore.acquire(timeout=limit):
            raise LlmError("kein freier Platz für einen b-api-Aufruf innerhalb des Zeitlimits")
        try:
            remaining = max(1.0, limit - (time.monotonic() - began))
            return self._client.request(method, url, json=json_body, timeout=remaining)
        finally:
            self._semaphore.release()

    def _trip(self) -> None:
        self._open_until = self._clock() + BREAKER_S

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "***")


def _parse_completion(data: Any, model: str, prompt_text: str) -> ChatResult:
    try:
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content")
        if isinstance(content, list):  # content parts
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if content is not None and not isinstance(content, str):
            raise TypeError("content is neither text nor a list of parts")
        text = (content or "").strip()
        if not text:  # some academiccloud models answer in the reasoning field only
            reasoning = message.get("reasoning") or message.get("reasoning_content")
            text = reasoning.strip() if isinstance(reasoning, str) else ""
        finish_reason = str(choice.get("finish_reason") or "")
        answered_by = str(data.get("model") or model)
        usage = data.get("usage")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise LlmError("b-api antwortete in einem unerwarteten Format") from exc
    prompt_tokens, completion_tokens, total_tokens = _usage(usage)
    if not prompt_tokens and not completion_tokens:
        # Without usable usage the budget would stop counting: estimate from the texts instead.
        prompt_tokens, completion_tokens = estimate_tokens(prompt_text), estimate_tokens(text)
        total_tokens = prompt_tokens + completion_tokens
    return ChatResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model=answered_by,
        finish_reason=finish_reason,
    )


def _usage(usage: Any) -> tuple[int, int, int]:
    """Prompt, completion and total tokens; zeros when the field is missing or malformed."""
    if not isinstance(usage, dict):
        return 0, 0, 0

    def number(key: str) -> int:
        value = usage.get(key)
        return int(value) if isinstance(value, int | float) and value > 0 else 0

    prompt_tokens, completion_tokens = number("prompt_tokens"), number("completion_tokens")
    return prompt_tokens, completion_tokens, number("total_tokens") or prompt_tokens + completion_tokens
