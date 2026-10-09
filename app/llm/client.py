"""b-api client (PLAN.md 7): OpenAI-compatible chat completions behind the ``X-API-KEY`` header.

Measured against ``b-api.staging.openeduhub.net`` on 2026-09-17: the path is
``/api/v1/llm/{provider}/chat/completions``; the reasoning models - GPT-5, GPT-6 (2026-09-24, D44) and
the o-series - take ``max_completion_tokens``, ``reasoning_effort`` and ``verbosity`` and reject
``temperature``; classic models take ``max_tokens`` and ``temperature``; Qwen3 models need ``chat_template_kwargs``
``{"enable_thinking": false}``. ``/models`` lists ``status`` and ``demand`` only for academiccloud.

The provider ``router`` is the b-api's routing (D97, measured on staging 2026-10-09): ``model`` names a route, set up
beforehand for the key or for all, which hands the request unchanged to one of its models; its ``/models`` lists the
routes, and the answer names the model that answered. A route bundles models of one parameter family, so the
parameters follow ``model``, the family, and the route name travels as ``route``.
"""

from __future__ import annotations

import logging
import math
import random
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.http_body import ACCEPT_ENCODING, UnreadableAnswerError, read_bounded
from app.llm.budget import estimate_tokens
from app.llm.deadline import MIN_CALL_S, Deadline

log = logging.getLogger(__name__)

# A gateway may pass an outage of the provider on as 500 (audit 2026-09-28, BE-14): it is retried and counts towards
# the breaker like 502 to 504; 501 says the gateway lacks the call, which no retry changes
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Behind a 502 or 504 the gateway gave up waiting for the model, which may have read the prompt; a 429 or 503 turned
# the request away before (audit 2026-09-27, KO-06)
REACHED_STATUSES = frozenset({502, 504})
# A refused key, permission or model does not fix itself within a request: calls stop for as long as an unavailable
# model waits for its re-check (gateway.RECHECK_S), and /health says why (audit 2026-09-27, BE-04)
REFUSED_STATUSES = frozenset({401, 403, 404})
AUTH_SUSPEND_S = 600.0
HIGH_DEMAND = 3  # academiccloud reported demand 0 to 2 in normal operation (2026-09-17)
MODEL_CHECK_TIMEOUT_S = 10.0  # the model list is a probe (start-up, health): one short attempt, no retries
TRIP_TIMEOUT_S = 30.0  # a call cut short by the request deadline is no outage; half a minute of silence is
# After a timeout, or after as many failed attempts in a row as a call may make (connection errors, 429 and 5xx, over
# all calls), calls fail fast instead of queueing on the next failure; then a single call probes (audit KO-05)
BREAKER_S = 60.0
SUSPENDED_MESSAGE = "b-api nach wiederholten Fehlern vorübergehend ausgesetzt"
QUEUE_TIME_UP = "Zeitbudget der Anfrage erschöpft, während der Aufruf auf einen freien Platz wartete"
_RETRY_AFTER_RE = re.compile("[0-9]{1,5}")  # Retry-After in seconds; a date is ignored and the backoff applies
_KEY_RE = re.compile(r"^[!-~]+$")  # printable ASCII without spaces; anything else breaks the header
# gpt-6-luna answers max_tokens with HTTP 400 and asks for max_completion_tokens (2026-09-24, D44)
_REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")
# Reasoning models count their thinking in max_completion_tokens; gpt-5.6-luna (reasoning_effort=low) used a
# block's whole limit of 555 tokens for it and answered with nothing (finish_reason=length, 2026-09-19)
REASONING_ALLOWANCE = 1000
# No call spends more: the largest windows hold about a million tokens. A broken or hostile gateway's usage of 2^63
# raised out of the budget store and stood in the day's counter until midnight (audit 2026-09-28, KO-26)
MAX_USAGE = 10_000_000
# An answer is read up to this many bytes (audit 2026-10-03, F12). A completion holds at most the output limit of
# its call, 4,000 tokens or some 16 KB of text for the longest block (MAX_FULL_OUTPUT_TOKENS); the model list was
# not measured. Parsed, JSON of many small objects takes 19 times its size (review of 2026-10-08)
MAX_ANSWER_BYTES = 16 * 1024 * 1024
_KEPT_HEADERS = frozenset({"content-type", "retry-after"})  # what the attempts read of an answer's headers
ROUTER = "router"  # the provider path of the b-api's routing (D97)
# The router's answers no retry mends (staging, 2026-10-09): a route unknown or switched off, a model of it without a
# price or one that cannot chat. It answers within 0.15 s, having tried its deployments; a retry got the same answer
# after 15 s (b-api test of 2026-10-01). With no deployment left the calls wait as after an outage: deployments the
# router paused after errors come back. Status, words of the answer, seconds held back, why
ROUTE_STOPS = (
    (
        400,
        "No route configured",
        AUTH_SUSPEND_S,
        "Route {route!r} ist in der b-api weder für den Schlüssel noch global aktiv; Route anlegen oder "
        "B_API_ROUTE prüfen",
    ),
    (
        503,
        "NOT_ELIGIBLE",
        AUTH_SUSPEND_S,
        "ein Modell der Route {route!r} beantwortet keine Chat-Anfragen (NOT_ELIGIBLE); Modelle der Route prüfen",
    ),
    (
        503,
        "Model pricing unavailable",
        AUTH_SUSPEND_S,
        "ein Modell der Route {route!r} hat in der b-api keinen Preis; Modellnamen der Route prüfen",
    ),
    (503, "No deployment could serve", BREAKER_S, "kein Modell der Route {route!r} ist aktiv oder erreichbar"),
)
# OpenAI's codes for a parameter the model does not take: a route of another family than B_API_MODEL refuses so
_FAMILY_CODES = ("unsupported_parameter", "unsupported_value")

Message = Mapping[str, str]


class LlmError(RuntimeError):
    """The b-api did not deliver a usable answer; ``status`` is the HTTP status when there was one, ``reached`` the
    number of attempts that may have reached the model and so may have cost the prompt's tokens, ``usage`` the prompt,
    completion and total tokens an answer reported that could not be used (audit 2026-09-29, A05)."""

    def __init__(
        self, message: str, status: int | None = None, reached: int = 0, usage: tuple[int, int, int] = (0, 0, 0)
    ) -> None:
        super().__init__(message)
        self.status = status
        self.reached = reached
        self.usage = usage


class LlmHeldBackError(LlmError):
    """The call never went out: the breaker holds the calls back, or the request's time ran out while the call waited
    for a free slot. No failure of the b-api of its own: the breaker logs its change once, and the line of the request
    counts the fallback (logging review of 2026-10-08)."""


@dataclass(frozen=True)
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    finish_reason: str
    # attempts before the answer that may have reached the model: a 502 or 504 (audit 2026-09-28, KO-27)
    reached_before: int = 0
    # prompt tokens the model read from its prompt cache, part of prompt_tokens (D69): the b-api passes the cache
    # through, a second call with the same opening of 3,507 tokens read 3,481 of them (2026-10-01)
    cached_tokens: int = 0
    # The answer ended with a line break, which the strip of ``text`` removes: cut at the output limit, its last line
    # is whole (review of 2026-10-08)
    ended_line: bool = False


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
    """GPT-5, GPT-6 and o-series models: completion-token limit, reasoning effort, verbosity, no temperature."""
    return model.lower().startswith(_REASONING_PREFIXES)


def needs_thinking_off(model: str) -> bool:
    return "qwen3" in model.lower()


class BApiClient:
    """Synchronous client with a concurrency semaphore, exponential backoff on 429/502/503/504 within one deadline
    for all attempts, and a circuit breaker."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        provider: str,
        model: str,
        route: str = "",
        timeout_s: float = 120.0,
        max_concurrency: int = 4,
        attempts: int = 3,
        backoff_s: float = 1.5,
        reasoning_effort: str = "low",
        reasoning_efforts: Mapping[str, str] | None = None,
        verbosity: str = "low",
        temperature: float = 0.2,
        response_cache: bool = False,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        api_key = api_key.strip()  # secret files usually end with a newline
        if not api_key:
            raise ValueError("b-api key is empty (B_API_KEY)")
        if not _KEY_RE.match(api_key):  # never echo the value
            raise ValueError("B_API_KEY contains whitespace or non-printable characters")
        self._key = api_key
        self._clock = clock
        self._jitter = jitter  # a draw in [0, 1): spreads a backoff between half and one and a half times its value
        self._state = threading.Lock()
        self._open_until = 0.0  # the breaker opens until then; after a break it stays in the past until a probe
        self._suspension = SUSPENDED_MESSAGE  # why calls fail fast
        self._probing = False
        self._failures = 0  # failed attempts in a row over all calls
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.model = model
        # The route the router gets; without one a route named like the model, the b-api's way to switch without an
        # outage. The other providers take the model itself (D97)
        self.route = (route.strip() or model) if provider == ROUTER else ""
        self._answering: set[str] = set()  # the models that answered behind the route
        self.timeout_s = timeout_s
        self.attempts = max(1, attempts)
        self.backoff_s = backoff_s
        self.reasoning_effort = reasoning_effort
        # LLM_REASONING_EFFORTS: the questions that think otherwise, by prompt id (M59)
        self.reasoning_efforts = dict(reasoning_efforts or {})
        self.verbosity = verbosity
        self.temperature = temperature
        self.response_cache = response_cache  # B_API_RESPONSE_CACHE (D70)
        self._sleep = sleep
        self.max_concurrency = max(1, max_concurrency)
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self._client = httpx.Client(
            headers={"X-API-KEY": api_key, "Accept": "application/json", "Accept-Encoding": ACCEPT_ENCODING},
            timeout=timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    @property
    def suspended(self) -> bool:
        """True while the circuit breaker is open: after a timeout, repeated failures or a refused key or model."""
        return self._clock() < self._open_until

    @property
    def suspension_reason(self) -> str:
        return self._suspension

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/api/v1/llm/{self.provider}/chat/completions"

    @property
    def models_url(self) -> str:
        return f"{self.base_url}/api/v1/llm/{self.provider}/models"

    def chat(
        self,
        messages: Sequence[Message],
        *,
        max_output_tokens: int,
        timeout_s: float | None = None,
        before_retry: Callable[[], str | None] | None = None,
        prompt: str | None = None,
        request: Deadline | None = None,
    ) -> ChatResult:
        """One chat completion; raises ``LlmError`` when the API fails or answers in an unexpected format.

        ``timeout_s`` shortens the configured timeout, e.g. to what is left of the request deadline. ``request`` is
        the deadline of the request the call belongs to: the call may wait as long as it has left for a free call
        slot, less ``MIN_CALL_S``, and its own time starts once it has one (D93); a request whose time ended while
        the call waited, as the parts beside a failed part 1 do, sends nothing. Without it the wait counts against
        ``timeout_s``. ``before_retry`` is
        asked before each retry after an attempt that may have reached the model; a reason instead of ``None`` ends
        the call with the attempts made (the budget has no room for another prompt, audit 2026-09-29, L1).
        ``prompt`` names the question, whose reasoning effort ``reasoning_efforts`` may set (M59).
        """
        body = self._body(messages, max_output_tokens, prompt)
        data, reached = self._request(
            "POST", self.chat_url, json_body=body, timeout_s=timeout_s, before_retry=before_retry, request=request
        )
        try:
            result = _parse_completion(data, self.model, "".join(str(m.get("content", "")) for m in messages))
        except LlmError as exc:
            # The model answered, so the attempt was paid: by what its usage reports, else like an attempt behind a
            # 504, and the attempts before it too; both used to count nothing (audit 2026-09-29, A05)
            usage = _usage(data.get("usage")) if isinstance(data, dict) else (0, 0, 0)
            raise LlmError(str(exc), 200, reached=reached if usage[2] else reached + 1, usage=usage) from exc
        if self.route:
            self._note_model(result.model)
        return replace(result, reached_before=reached) if reached else result

    def models(self) -> list[ModelInfo]:
        data, _ = self._request("GET", self.models_url, attempts=1, timeout_s=MODEL_CHECK_TIMEOUT_S)
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
                    demand=_whole(demand),
                )
            )
        return infos

    def check_model(self) -> ModelCheck:
        """Compare the configured model - with the router its route - with ``/models``; never raises, the caller
        decides what to do."""
        name = self.route or self.model
        try:
            infos = self.models()
        except LlmError as exc:
            return ModelCheck(False, name, False, None, None, f"b-api nicht erreichbar: {exc}")
        info = next((m for m in infos if m.id == name), None)
        if info is None:
            if "/" in self.route:
                # provider/model reaches that provider without a route and is never listed (b-api, 2026-10-02)
                message = f"{name} ohne Route: die b-api fragt den Provider davor direkt, ohne Ausweichen"
                return ModelCheck(True, name, False, None, None, message)
            if self.route:
                message = (
                    f"Route {name!r} steht nicht in /models des Routers: In der b-api ist weder für den Schlüssel "
                    "noch global eine aktive Route dieses Namens; Route anlegen oder B_API_ROUTE prüfen"
                )
            else:
                message = f"Modell {self.model!r} steht nicht in /models des Providers {self.provider}"
            return ModelCheck(False, name, False, None, None, message)
        if info.status is not None and info.status != "ready":
            return ModelCheck(False, name, True, info.status, info.demand, f"Modell {name} hat status {info.status}")
        if info.demand is not None and info.demand >= HIGH_DEMAND:
            message = f"Modell {name} ist stark ausgelastet (demand {info.demand})"
            return ModelCheck(False, name, True, info.status, info.demand, message)
        message = f"Route {name} verfügbar, Parameter wie {self.model}" if self.route else f"Modell {name} verfügbar"
        return ModelCheck(True, name, True, info.status, info.demand, message)

    def completion_limit(self, answer_tokens: int) -> int:
        """The API's output limit for an answer of ``answer_tokens``: reasoning models also spend it on thinking."""
        return answer_tokens + REASONING_ALLOWANCE if is_reasoning_model(self.model) else answer_tokens

    def _body(self, messages: Sequence[Message], max_output_tokens: int, prompt: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.route or self.model, "messages": [dict(m) for m in messages]}
        if is_reasoning_model(self.model):
            body["max_completion_tokens"] = max_output_tokens
            body["reasoning_effort"] = self.reasoning_efforts.get(prompt or "", self.reasoning_effort)
            body["verbosity"] = self.verbosity
        else:
            body["max_tokens"] = max_output_tokens
            body["temperature"] = self.temperature
            if needs_thinking_off(self.model):
                body["chat_template_kwargs"] = {"enable_thinking": False}
        if not self.response_cache:
            # The b-api answers a request it has seen word for word from a store (same id, 0.4 instead of 3.8 s,
            # measured 2026-10-01, D70); an identifier of its own makes every call new. Not ``user``: that one also
            # scattered the provider's prompt cache, this one left it whole. Both providers accept it.
            body["safety_identifier"] = uuid.uuid4().hex
        return body

    def _request(
        self,
        method: str,
        url: str,
        json_body: Mapping[str, Any] | None = None,
        *,
        attempts: int | None = None,
        timeout_s: float | None = None,
        before_retry: Callable[[], str | None] | None = None,
        request: Deadline | None = None,
    ) -> tuple[Any, int]:
        """One call: attempts until an answer, all of them within one deadline; with the answer, how many attempts
        before it may have reached the model. Every retry used to get the whole
        limit again, so a call outlived the deadline of its request (audit 2026-09-27, KO-04)."""
        now = self._clock()
        ends = now + (timeout_s if timeout_s is not None else self.timeout_s)
        hard_end = now + request.remaining() if request is not None else None
        probe = self._admit()
        try:
            # After a break a single attempt decides whether the b-api is back
            tries = 1 if probe else attempts or self.attempts
            return self._attempts(method, url, json_body, tries, (ends, hard_end), before_retry, request)
        finally:
            if probe:
                with self._state:
                    self._probing = False  # a probe that neither closed nor tripped the breaker lets the next one try

    def _attempts(
        self,
        method: str,
        url: str,
        json_body: Mapping[str, Any] | None,
        attempts: int,
        window: tuple[float, float | None],
        before_retry: Callable[[], str | None] | None,
        request: Deadline | None = None,
    ) -> tuple[Any, int]:
        """The attempts of one call until ``ends``; the wait for a call slot moves ``ends`` up to ``hard_end``, the end
        of the call's request, where the caller named it (D93)."""
        ends, hard_end = window
        last_error = ""
        status: int | None = None
        reached = 0
        for attempt in range(attempts):
            limit = ends - self._clock()
            had = limit  # the time the attempt had for itself once it held a call slot
            try:
                with self._slot(limit, hard_end, request) as (had, waited):
                    if hard_end is not None:
                        ends = min(ends + waited, hard_end)  # the wait was the request's time, not the call's
                    response = self._send(method, url, json_body, had)
            except UnreadableAnswerError as exc:
                # the model answered, so the attempt may have cost its prompt (A05)
                raise LlmError(f"b-api antwortete mit {exc}", reached=reached + 1) from exc
            except LlmError as exc:
                # No free call slot in time: a full queue on our side, no outage, but the attempts before it may have
                # reached the model and cost their prompts (audit 2026-09-29, A05)
                raise type(exc)(str(exc), reached=reached) from exc
            except httpx.TimeoutException as exc:
                # A request that timed out once will not answer in time on a retry within a synchronous request.
                reached += isinstance(exc, httpx.ReadTimeout | httpx.WriteTimeout)
                # Silence is an outage only where the attempt had the time: a wait in the queue that left a call 20 of
                # its 120 s is none (D93)
                if had >= min(self.timeout_s, TRIP_TIMEOUT_S):
                    self._trip(cause=f"no answer within {had:.0f} s ({type(exc).__name__})")
                # The seconds the attempt had: a call the deadline left 6 s read like an outage (logging review)
                message = f"b-api antwortete nicht rechtzeitig ({type(exc).__name__} nach {had:.0f} s)"
                raise LlmError(message, reached=reached) from exc
            except httpx.HTTPError as exc:
                # httpx quotes illegal header values (the key) in its messages: redact before the text travels on.
                last_error, status = self._redact(f"{type(exc).__name__}: {exc}"), None
                wait = self._backoff(attempt)
            else:
                status = response.status_code
                if status == 200:
                    self._close()
                    try:
                        return response.json(), reached
                    except (ValueError, RecursionError) as exc:  # also a nesting too deep to read
                        # the model answered: the attempt may have cost its prompt like one behind a 504 (A05)
                        raise LlmError("b-api antwortete ohne gültiges JSON", status, reached=reached + 1) from exc
                stop = self._route_stop(status, response.text) if self.route else None
                if status not in RETRY_STATUSES or stop is not None:
                    # The upstream body stays in the log: messages reach /health, the audit and the frontmatter. The
                    # key is blanked before the cut, which otherwise left the start of an echoed key (SE-10).
                    # on one line: the CR and LF of an error page split a record of the plain format (logging review)
                    log.warning(
                        "b-api answered HTTP %s: %s%s",
                        status,
                        " ".join(self._redact(response.text)[:200].split()),
                        self._family_hint(status, response.text),
                    )
                    if stop is not None:
                        seconds, why = stop
                        span = f"{round(seconds / 60)} Minuten" if seconds >= 120 else f"{seconds:.0f} s"
                        self._trip(seconds, f"b-api-Routing {span} ausgesetzt: {why}", cause=f"HTTP {status}")
                        raise LlmError(f"b-api antwortete HTTP {status}: {why}", status, reached=reached)
                    if status in REFUSED_STATUSES:
                        self._refused(status)
                    elif status < 500:
                        self._close()  # the b-api answers; the request was wrong
                    raise LlmError(f"b-api antwortete HTTP {status}", status, reached=reached)
                last_error = f"HTTP {status}"
                reached += status in REACHED_STATUSES
                wait = _retry_after(response) or self._backoff(attempt)
            with self._state:
                self._failures += 1
            if attempt + 1 >= attempts:
                break
            if ends - self._clock() - wait < MIN_CALL_S:
                last_error = f"{last_error}, keine Wiederholung: keine Zeit für {wait:.0f} s Wartezeit"
                break
            if before_retry is not None and status in REACHED_STATUSES:
                refusal = before_retry()
                if refusal is not None:
                    last_error = f"{last_error}, keine Wiederholung: {refusal}"
                    break
            # A 429 or 5xx retried into an answer left no trace, the seconds slept among it (logging review)
            log.info("b-api %s on attempt %d of %d, retrying in %.1f s", last_error, attempt + 1, attempts, wait)
            self._sleep(wait)
        if self._failures >= self.attempts:
            self._trip(cause=f"{self._failures} failed attempts in a row, the last {last_error}")
        raise LlmError(f"b-api nach {attempt + 1} Versuchen nicht erreichbar ({last_error})", status, reached=reached)

    def _backoff(self, attempt: int) -> float:
        """Exponential, spread around its value: calls that failed together should not all come back together."""
        return float(self.backoff_s * 2**attempt * (0.5 + self._jitter()))

    def _admit(self) -> bool:
        """Raise while the breaker is open; ``True`` when this call is the one probe after a break."""
        with self._state:
            if self._clock() < self._open_until or self._probing:
                raise LlmHeldBackError(self._suspension)
            if not self._open_until:
                return False
            self._probing = True
        log.info("b-api probe after the break: this call decides whether the calls resume")
        return True

    def _route_stop(self, status: int, text: str) -> tuple[float, str] | None:
        """How long the calls wait and why, when the router answered what no retry mends (``ROUTE_STOPS``)."""
        for code, words, seconds, why in ROUTE_STOPS:
            if status == code and words in text:
                return seconds, why.format(route=self.route)
        return None

    def _family_hint(self, status: int, text: str) -> str:
        """Behind a route the provider's refusal of a parameter: the route bundles models of another family than
        B_API_MODEL, whose parameters the service sends (D97)."""
        if not self.route or status != 400 or not any(code in text for code in _FAMILY_CODES):
            return ""
        return (
            f" - route {self.route!r} leads to a model that refuses the parameters of B_API_MODEL={self.model}; a "
            "route bundles models of one parameter family"
        )

    def _note_model(self, model: str) -> None:
        """Name once which model answers behind the route: the answer names the model, not the deployment, and a
        new one shows the route turned to another, its reserve (D97)."""
        with self._state:
            new = model not in self._answering
            self._answering.add(model)
        if new:
            log.info("b-api routing: route %r answers with %s", self.route, model)

    def _refused(self, status: int) -> None:
        minutes = round(AUTH_SUSPEND_S / 60)
        reason = f"b-api {minutes} Minuten ausgesetzt: HTTP {status}, Schlüssel, Berechtigung oder Modell prüfen"
        self._trip(AUTH_SUSPEND_S, reason, cause=f"HTTP {status}")

    @contextmanager
    def _slot(
        self, limit: float, hard_end: float | None, request: Deadline | None = None
    ) -> Iterator[tuple[float, float]]:
        """A free call slot for one attempt; yields the time the attempt has and how long it waited for the slot.

        Without ``hard_end`` the wait counts against ``limit`` like the request itself. With it, the end of the
        request the call belongs to, the call may wait until ``MIN_CALL_S`` before that end and then has ``limit``
        for itself, no more than the request has left: on academiccloud's two slots the wait ate most of a call's
        own time (D93).
        """
        began = self._clock()  # the client's one clock: the real one mixed in drifted from an injected one
        patience = limit if hard_end is None else hard_end - began - MIN_CALL_S
        if not self._semaphore.acquire(timeout=max(0.0, patience)):
            raise LlmHeldBackError("kein freier Platz für einen b-api-Aufruf innerhalb des Zeitlimits")
        try:
            # The request's time can end while the call waits: part 1 failed, and the parts beside it stop
            # (Deadline.expire). Its call goes out no more (review of 2026-10-08)
            if request is not None and request.remaining() < MIN_CALL_S:
                raise LlmHeldBackError(QUEUE_TIME_UP)
            waited = self._clock() - began
            time_left = limit - waited if hard_end is None else min(limit, hard_end - began - waited)
            yield max(1.0, time_left), waited
        finally:
            self._semaphore.release()

    def _send(self, method: str, url: str, json_body: Mapping[str, Any] | None, limit: float) -> httpx.Response:
        """One HTTP attempt of at most ``limit`` seconds, made holding a call slot (``_slot``). The answer is read up
        to ``MAX_ANSWER_BYTES`` (``AnswerTooLargeError`` past it, ``UnreadableAnswerError`` in a coding it does not
        unpack) and comes back read, with the headers a caller looks at."""
        request = self._client.build_request(method, url, json=json_body, timeout=limit)
        streamed = self._client.send(request, stream=True)
        try:
            body = read_bounded(streamed, MAX_ANSWER_BYTES)
        finally:
            streamed.close()
        # decoded already: without the headers of the transfer, which would have it decoded a second time
        kept = {name: value for name, value in streamed.headers.items() if name.lower() in _KEPT_HEADERS}
        return httpx.Response(streamed.status_code, headers=kept, content=body, request=request)

    def _trip(self, seconds: float = BREAKER_S, reason: str = SUSPENDED_MESSAGE, *, cause: str) -> None:
        """Hold the calls back for ``seconds``. The change is logged once, with what caused it: the breaker wrote no
        line, while every call that met it logged a WARNING (logging review of 2026-10-08)."""
        with self._state:
            opening = self._clock() >= self._open_until  # closed, or waiting for its probe
            self._open_until = self._clock() + seconds
            self._suspension = reason
            self._probing = False
        if opening:
            log.warning("b-api calls held back for %.0f s: %s (%s)", seconds, reason, cause)

    def _close(self) -> None:
        """The b-api answered: the breaker closes and the failures in a row start again at zero."""
        with self._state:
            resumed = self._open_until != 0.0
            self._open_until = 0.0
            self._probing = False
            self._failures = 0
        if resumed:
            log.info("b-api answers again; the calls resume")

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "***")


def _retry_after(response: httpx.Response) -> float | None:
    """The seconds a 429 or 503 asks to wait, when it says so as a number."""
    value = response.headers.get("retry-after", "").strip()
    return float(value) if _RETRY_AFTER_RE.fullmatch(value) else None


# Signs str.strip() keeps: a byte order mark and a zero-width space around an answer of nothing else made a written
# block, and before "p1 praxis 8" they hid the paragraph (review of 2026-10-08)
_INVISIBLE = chr(0xFEFF) + chr(0x200B)


def _trimmed(text: str) -> str:
    """``text`` without white space and invisible signs around it."""
    previous = None
    while previous != text:
        previous, text = text, text.strip().strip(_INVISIBLE)
    return text


def _parse_completion(data: Any, model: str, prompt_text: str) -> ChatResult:
    try:
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content")
        if isinstance(content, list):  # content parts
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if content is not None and not isinstance(content, str):
            raise TypeError("content is neither text nor a list of parts")
        text = _trimmed(content or "")
        ended_line = (content or "").rstrip(" \t").endswith("\n")
        finish_reason = str(choice.get("finish_reason") or "")
        # Some academiccloud models answer in the reasoning field only. Cut off at the output limit it holds a thought,
        # not an answer: the article choice read {"wahl": 3} from one, the synthesis printed thoughts as model
        # knowledge (audit 2026-09-29, L2); the call then answered nothing, and its caller says so
        if not text and finish_reason != "length":
            reasoning = message.get("reasoning") or message.get("reasoning_content")
            text = _trimmed(reasoning) if isinstance(reasoning, str) else ""
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
        cached_tokens=_cached(usage, prompt_tokens),
        ended_line=ended_line,
    )


def _whole(value: Any) -> int | None:
    """A JSON number as an int; ``None`` for anything else. json.loads reads Infinity and NaN, and int() refuses
    both (audit 2026-09-27, KO-03)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return int(value)


def _cached(usage: Any, prompt_tokens: int) -> int:
    """The prompt tokens read from the prompt cache (``prompt_tokens_details.cached_tokens``); never more than the
    prompt, zero when the field is missing or malformed."""
    details = usage.get("prompt_tokens_details") if isinstance(usage, dict) else None
    value = _whole(details.get("cached_tokens")) if isinstance(details, dict) else None
    return min(value, prompt_tokens) if value is not None and value > 0 else 0


def _usage(usage: Any) -> tuple[int, int, int]:
    """Prompt, completion and total tokens; zeros when the field is missing or malformed."""
    if not isinstance(usage, dict):
        return 0, 0, 0

    def number(key: str) -> int:
        value = _whole(usage.get(key))
        return min(value, MAX_USAGE) if value is not None and value > 0 else 0

    prompt_tokens, completion_tokens = number("prompt_tokens"), number("completion_tokens")
    return prompt_tokens, completion_tokens, number("total_tokens") or prompt_tokens + completion_tokens
