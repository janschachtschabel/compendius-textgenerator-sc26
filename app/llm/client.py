"""b-api client (PLAN.md 7): OpenAI-compatible chat completions with the key of the request or the service (D105).

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
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from typing import Any, Literal, NoReturn

import httpx

from app.http_body import ACCEPT_ENCODING, UnreadableAnswerError, read_bounded
from app.llm.budget import estimate_tokens
from app.llm.credentials import X_API_KEY, RequestKey, own_key_only, request_key
from app.llm.deadline import MIN_CALL_S, Deadline
from app.llm.routing import ROUTER, family_hint, no_route, route_name, route_stop
from app.tracing import outgoing_headers

log = logging.getLogger(__name__)

# A gateway may pass an outage of the provider on as 500 (audit 2026-09-28, BE-14): it is retried and counts towards
# the breaker like 502 to 504; 501 says the gateway lacks the call, which no retry changes
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Behind a 502 or 504 the gateway gave up waiting for the model, which may have read the prompt; a 429 or 503 turned
# the request away before (audit 2026-09-27, KO-06)
REACHED_STATUSES = frozenset({502, 504})
# A refused key, permission or model does not fix itself within a request: calls stop for as long as an unavailable
# model waits for its re-check (gateway.RECHECK_S), and /health says why (audit 2026-09-27, BE-04)
REFUSED_STATUSES = frozenset({401, 402, 403, 404})
# What the b-api answers a key it will not serve: one unknown or switched off, a limit reached - 402 is the usual answer
# to a cost limit, which status the b-api sends was not documented on 2026-10-14 -, a right missing. With the key of a
# request only that request loses the LLM; with the service's own, all calls wait (D106)
KEY_REFUSALS = frozenset({401, 402, 403})
AUTH_SUSPEND_S = 600.0
NO_KEY = "kein b-api-Schlüssel: die Anfrage brachte keinen (Authorization oder X-API-Key), und B_API_KEY ist leer"
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
# raised out of the day's store, gone since D104, and would inflate a request's budget and the token metrics
# (audit 2026-09-28, KO-26)
MAX_USAGE = 10_000_000
# An answer is read up to this many bytes (audit 2026-10-03, F12). A completion holds at most the output limit of
# its call, 4,000 tokens or some 16 KB of text for the longest block (MAX_FULL_OUTPUT_TOKENS); the model list was
# not measured. Parsed, JSON of many small objects takes 19 times its size (review of 2026-10-08)
MAX_ANSWER_BYTES = 16 * 1024 * 1024
# What the attempts read of an answer's headers; X-Error-Source: upstream marks what the provider sent on (2026-10-09)
_KEPT_HEADERS = frozenset({"content-type", "retry-after", "x-error-source"})
# The names of models answering behind a route a worker notes in its log: the field comes from upstream (D98)
MAX_NOTED_MODELS = 32
# A b-api without the routing answers the router's paths with 404 (D98)
_NO_ROUTER = "die b-api kennt kein Routing; B_API_PROVIDER und B_API_BASE_URL prüfen, nicht jede b-api hat es schon"

Message = Mapping[str, str]


class _NoCookies(DefaultCookiePolicy):
    """Takes no cookie: the b-api's answers to one caller's key must not travel with another's calls."""

    def set_ok(self, cookie: Cookie, request: urllib.request.Request) -> bool:
        return False


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


class LlmKeyRefusedError(LlmError):
    """The b-api refused the key of the request being handled (D106); the line that says so is written once per
    request, so the calls that meet it log no line of their own."""


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
    """GPT-5, GPT-6 and o-series models: completion-token limit, reasoning effort, verbosity, no temperature. A model
    named with its provider, as the router takes it (openai/gpt-6-luna), is judged by the model (D98)."""
    return model.lower().rpartition("/")[2].startswith(_REASONING_PREFIXES)


def needs_thinking_off(model: str) -> bool:
    return "qwen3" in model.lower()


def parameter_family(model: str) -> tuple[bool, bool]:
    """What decides the parameters the service sends a model (``BApiClient._body``)."""
    return is_reasoning_model(model), needs_thinking_off(model)


# The model of an answer behind a route that names none: B_API_MODEL stood there, as though it had answered (review
# of 2026-10-17)
UNKNOWN_MODEL = "unbekannt"


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
        api_key = api_key.strip()  # secret files usually end with a newline; empty: each request brings its key
        if api_key and not _KEY_RE.match(api_key):  # never echo the value
            raise ValueError("B_API_KEY contains whitespace or non-printable characters")
        self._key = api_key
        self._clock = clock
        self._jitter = jitter  # a draw in [0, 1): spreads a backoff between half and one and a half times its value
        self._state = threading.Lock()
        self._open_until = 0.0  # the breaker opens until then; after a break it stays in the past until a probe
        self._suspension = SUSPENDED_MESSAGE  # why calls fail fast
        # A stop on the service's own key - refused, or its route down - holds back only the calls that carry that key,
        # not those with a key of their request, whose limits are their own (review of D105/D106). Its own deadline:
        # an outage within its ten minutes concerns every key (audit 2026-10-16)
        self._own_key_until = 0.0
        self._own_key_suspension = SUSPENDED_MESSAGE
        self._probing = False  # a probe after an outage: every call waits for it
        self._own_key_probing = False  # a probe after a stop on the own key: the calls with that key wait for it
        self._failures = 0  # failed attempts in a row over all calls
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.model = model
        # The route the router gets; without one a route named like the model, the b-api's way to switch without an
        # outage. The other providers take the model itself (D97)
        self.route = route_name(provider, model, route)
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
            # the key goes with each call, the request's or the service's own, never both (D105)
            headers={"Accept": "application/json", "Accept-Encoding": ACCEPT_ENCODING},
            # the client serves all requests with their callers' keys: no cookie of one call reaches the next
            cookies=CookieJar(policy=_NoCookies()),
            timeout=timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    @property
    def suspended(self) -> bool:
        """True while the circuit breaker holds back the calls of the request being handled: after a timeout,
        repeated failures, a refused model, or the service's own key refused - that one not for a request with a key
        of its own."""
        now = self._clock()
        return now < self._open_until or (request_key() is None and now < self._own_key_until)

    @property
    def suspension_reason(self) -> str:
        if request_key() is None and self._clock() >= self._open_until and self._own_key_until:
            return self._own_key_suspension
        return self._suspension

    @property
    def has_own_key(self) -> bool:
        """Whether the service has a key of its own (B_API_KEY); without one every call takes its request's (D105)."""
        return bool(self._key)

    def key_problem(self) -> str | None:
        """Why a call of the request being handled cannot go out for its key: the request's refused by the b-api
        (D106), or none at all; ``None`` while there is one."""
        key = request_key()
        if key is not None:
            return key.refused
        return None if self._key else NO_KEY

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
            answered = UNKNOWN_MODEL if self.route else self.model  # behind a route the reserve may have answered
            result = _parse_completion(data, answered, "".join(str(m.get("content", "")) for m in messages))
        except LlmError as exc:
            # The model answered, so the attempt was paid: by what its usage reports, else like an attempt behind a
            # 504, and the attempts before it too; both used to count nothing (audit 2026-09-29, A05)
            usage = _usage(data.get("usage")) if isinstance(data, dict) else (0, 0, 0)
            raise LlmError(str(exc), 200, reached=reached if usage[2] else reached + 1, usage=usage) from exc
        if self.route:
            self._note_model(result.model)
        return replace(result, reached_before=reached) if reached else result

    def models(self) -> list[ModelInfo]:
        with own_key_only():  # the check holds for all requests: never one caller's key decides it (D105)
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
            if self.route and exc.status == 404:
                message = f"{_NO_ROUTER} (HTTP 404 auf /api/v1/llm/{ROUTER}/models)"
                return ModelCheck(False, name, False, None, None, message)
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
            return self._attempts(method, url, json_body, tries, (ends, hard_end), before_retry, request, probe=probe)
        finally:
            # a probe that neither closed nor tripped the breaker lets the next one try - of its own kind only: an
            # outage's probe ended by the service's key let a second call go out beside it (review of 2026-10-17)
            if probe == "outage":
                with self._state:
                    self._probing = False
            elif probe == "own key":
                with self._state:
                    self._own_key_probing = False

    def _attempts(
        self,
        method: str,
        url: str,
        json_body: Mapping[str, Any] | None,
        attempts: int,
        window: tuple[float, float | None],
        before_retry: Callable[[], str | None] | None,
        request: Deadline | None = None,
        *,
        probe: Literal["", "outage", "own key"] = "",
    ) -> tuple[Any, int]:
        """The attempts of one call until ``ends``; the wait for a call slot moves ``ends`` up to ``hard_end``, the end
        of the call's request, where the caller named it (D93). ``probe`` names the stop this call probes after."""
        ends, hard_end = window
        last_error = ""
        status: int | None = None
        reached = 0
        for attempt in range(attempts):
            problem = self.key_problem()  # no key, or another call of the request met the b-api's refusal
            if problem is not None:
                raise LlmHeldBackError(problem, reached=reached)
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
                key = request_key()
                refused = status in KEY_REFUSALS or status == 404
                missing_route = bool(self.route) and no_route(status, response.text)
                if key is not None and (refused or stop is not None or missing_route):
                    # A route may belong to the key (D97): what it answers holds back this request, not every
                    # caller's, as a refused key does (audit 2026-10-15). A 404 too: whether the b-api means the key
                    # or the server by it was never measured, and one caller's key held back all (audit 2026-10-16)
                    if status in KEY_REFUSALS:
                        why = (
                            f"b-api lehnt den Schlüssel der Anfrage ab (HTTP {status}): Limit erreicht, LLM für den "
                            "Schlüssel abgeschaltet oder keine Berechtigung"
                        )
                    elif status == 404:
                        target = f"die Route {self.route!r}" if self.route else f"das Modell {self.model!r}"
                        why = f"b-api findet {target} für den Schlüssel der Anfrage nicht (HTTP 404)"
                    elif stop is None or missing_route:
                        why = f"Route {self.route!r} ist für den Schlüssel der Anfrage nicht aktiv (HTTP {status})"
                    else:
                        why = f"b-api-Routing für den Schlüssel der Anfrage ausgesetzt: {stop[1]} (HTTP {status})"
                    if status in KEY_REFUSALS:
                        label = "refused the key of this request"
                    elif self.route:
                        label = f"route {self.route!r} holds back this request"
                    else:
                        label = "found nothing for the key of this request"
                    raise self._refuse(key, why, response.text, status, reached, label=label)
                if status not in RETRY_STATUSES or stop is not None:
                    # The upstream body stays in the log: messages reach /health, the audit and the frontmatter. The
                    # key is blanked before the cut, which otherwise left the start of an echoed key (SE-10).
                    # on one line: the CR and LF of an error page split a record of the plain format (logging review)
                    log.warning(
                        "b-api answered HTTP %s: %s%s",
                        status,
                        " ".join(self._redact(response.text)[:200].split()),
                        family_hint(status, response.text, self.route, self.model),
                    )
                    if stop is not None:
                        seconds, why = stop
                        span = f"{round(seconds / 60)} Minuten" if seconds >= 120 else f"{seconds:.0f} s"
                        # met with the service's own key (a request key was refused above): a route may belong to a
                        # key (D97), the callers' own keys keep the LLM (review of the audit 2026-10-15)
                        self._trip(
                            seconds, f"b-api-Routing {span} ausgesetzt: {why}", cause=f"HTTP {status}", own_key=True
                        )
                        raise LlmError(f"b-api antwortete HTTP {status}: {why}", status, reached=reached)
                    if status in REFUSED_STATUSES:
                        self._refused(status, upstream=response.headers.get("x-error-source") == "upstream")
                    elif status < 500:
                        self._close()  # the b-api answers; the request was wrong
                    raise LlmError(f"b-api antwortete HTTP {status}", status, reached=reached)
                last_error = f"HTTP {status}"
                reached += status in REACHED_STATUSES
                wait = _retry_after(response) or self._backoff(attempt)
            if status != 429:
                # A 429 speaks of the key that met it, a caller's or the service's own: the count of failures in a row
                # stays with the b-api's state (D106, review of 2026-10-17)
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
        if status == 429:
            self._limited(attempt + 1, last_error, reached, probe)
        if self._failures >= self.attempts:
            self._trip(cause=f"{self._failures} failed attempts in a row, the last {last_error}")
        raise LlmError(f"b-api nach {attempt + 1} Versuchen nicht erreichbar ({last_error})", status, reached=reached)

    def _limited(self, made: int, said: str, reached: int, probe: Literal["", "outage", "own key"]) -> NoReturn:
        """The b-api answered 429 to the last of ``made`` attempts: it speaks of the key that met it, a caller's or the
        service's own, and of no outage - an answer, which closes no stop and opens none for the other keys; the
        failures in a row left from before made a probe trip the outage again (review of 2026-10-17)."""
        key = request_key()
        if key is not None and probe != "outage":  # the probe's one attempt may meet a passing 429
            why = f"b-api begrenzt den Schlüssel der Anfrage (HTTP 429 nach {made} Versuchen): Limit erreicht"
            raise self._refuse(key, why, said, 429, reached)
        if key is None and (made >= self.attempts or probe == "own key"):
            # after all its attempts, or its probe still limited; one 429 of the model check is no stop
            reason = f"b-api begrenzt den Schlüssel des Dienstes (HTTP 429 nach {made} Versuchen): Limit erreicht"
            self._trip(BREAKER_S, reason, cause=said, own_key=True)
        raise LlmError(f"b-api nach {made} Versuchen nicht erreichbar ({said})", 429, reached=reached)

    def _backoff(self, attempt: int) -> float:
        """Exponential, spread around its value: calls that failed together should not all come back together."""
        return float(self.backoff_s * 2**attempt * (0.5 + self._jitter()))

    def _admit(self) -> Literal["", "outage", "own key"]:
        """Raise while the breaker is open for this call; the kind of stop when it is the one probe after it."""
        own_key = request_key() is None
        kind: Literal["outage", "own key"]
        with self._state:
            now = self._clock()
            if now < self._open_until or self._probing:
                raise LlmHeldBackError(self._suspension)
            if own_key and (now < self._own_key_until or self._own_key_probing):
                raise LlmHeldBackError(self._own_key_suspension)
            if self._open_until:
                self._probing, kind = True, "outage"
            elif own_key and self._own_key_until:
                self._own_key_probing, kind = True, "own key"
            else:
                return ""
        log.info("b-api probe after the break: this call decides whether the calls resume")
        return kind

    def _route_stop(self, status: int, text: str) -> tuple[float, str] | None:
        """How long the calls wait and why, when the router answered what no retry mends (``routing.route_stop``):
        ten minutes for what lasts, as after a refused key, one minute for no deployment left, as after an outage."""
        stop = route_stop(status, text, self.route)
        if stop is None:
            return None
        lasting, why = stop
        return (AUTH_SUSPEND_S if lasting else BREAKER_S), why

    def _note_model(self, model: str) -> None:
        """Name once per worker which model answers behind the route: the answer names the model, not the
        deployment, and a new one shows the route turned to another, its reserve (D97). The name comes from upstream:
        on one line and of a sane length, without control signs, and no more than ``MAX_NOTED_MODELS`` of them (D98).
        A model of another parameter family than ``B_API_MODEL`` is a WARNING: it got that model's parameters, and one
        that took them answered without a word, a Qwen3 without its switch thinking at length (review of 2026-10-17)."""
        printable = "".join(sign for sign in model[:100] if sign.isprintable() or sign.isspace())
        name = " ".join(printable.split())
        with self._state:
            new = name not in self._answering and len(self._answering) < MAX_NOTED_MODELS
            if new:
                self._answering.add(name)
        if not new:
            return
        if name != UNKNOWN_MODEL and parameter_family(name) != parameter_family(self.model):
            log.warning(
                "b-api routing: route %r answers with %s, of another parameter family than B_API_MODEL=%s: the "
                "parameters it gets are those of B_API_MODEL; the route's models should be of one family (D97)",
                self.route,
                name,
                self.model,
            )
        else:
            log.info("b-api routing: route %r answers with %s", self.route, name)

    def _refuse(
        self,
        key: RequestKey,
        why: str,
        said: str,
        status: int,
        reached: int,
        *,
        label: str = "refused the key of this request",
    ) -> LlmError:
        """The b-api refused the key of the request being handled (D106), or its route for that key (D97): the rest
        of that request runs without the LLM, every other request keeps it. One line per request says so, with what
        the b-api answered - a route down named as such, not as a refused key (audit 2026-10-16)."""
        if key.refuse(why):
            log.warning(
                "b-api %s: %s (b-api: %s); the request goes on without the LLM (llm-free)",
                label,
                why,
                " ".join(self._redact(said)[:200].split()) or "-",
            )
        return LlmKeyRefusedError(why, status, reached=reached)

    def _refused(self, status: int, *, upstream: bool = False) -> None:
        """The service's own key met a refusal: its calls wait ten minutes, the callers' own keys keep the LLM (D106).
        Only a 404 of the b-api itself behind a route says it has no router, the same for every key; one the provider
        sent on (``X-Error-Source: upstream``), say for a model the route lost, does not (review of 2026-10-17)."""
        minutes = round(AUTH_SUSPEND_S / 60)
        if self.route and status == 404 and not upstream:
            reason = f"b-api-Routing {minutes} Minuten ausgesetzt: HTTP 404, {_NO_ROUTER}"
            self._trip(AUTH_SUSPEND_S, reason, cause=f"HTTP {status}")
            return
        if status in KEY_REFUSALS:
            reason = (
                f"b-api {minutes} Minuten ausgesetzt: HTTP {status}, die b-api lehnt den Schlüssel des Dienstes ab "
                "(Limit erreicht, LLM abgeschaltet oder keine Berechtigung); bis dahin llm-free"
            )
        else:
            source = " vom Anbieter" if upstream else ""
            reason = (
                f"b-api {minutes} Minuten ausgesetzt: HTTP {status}{source}, Schlüssel, Berechtigung oder Modell prüfen"
            )
        self._trip(AUTH_SUSPEND_S, reason, cause=f"HTTP {status}", own_key=True)

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
        """One HTTP attempt, made holding a call slot (``_slot``): ``limit`` seconds for each phase up to the answer's
        start, and what is left of them for reading its body (``read_bounded``): the body took its whole time again,
        twice the call's in all (audit 2026-10-16). The answer is read up to ``MAX_ANSWER_BYTES``
        (``AnswerTooLargeError`` past it, ``UnreadableAnswerError`` in a coding it does not unpack) and comes back
        read, with the headers a caller looks at."""
        headers = {**outgoing_headers(), **self._key_header()}  # the trace of the request goes on (D108)
        request = self._client.build_request(method, url, json=json_body, timeout=limit, headers=headers)
        started = self._clock()
        streamed = self._client.send(request, stream=True)
        try:
            left = max(0.0, limit - (self._clock() - started))
            body = read_bounded(streamed, MAX_ANSWER_BYTES, within=left)  # the body too (audit 2026-10-15)
        finally:
            streamed.close()
        # decoded already: without the headers of the transfer, which would have it decoded a second time
        kept = {name: value for name, value in streamed.headers.items() if name.lower() in _KEPT_HEADERS}
        return httpx.Response(streamed.status_code, headers=kept, content=body, request=request)

    def _trip(
        self, seconds: float = BREAKER_S, reason: str = SUSPENDED_MESSAGE, *, cause: str, own_key: bool = False
    ) -> None:
        """Hold the calls back for ``seconds``. Each change is logged once, with what caused it: the breaker wrote no
        line, while every call that met it logged a WARNING (logging review of 2026-10-08). A stop never cuts a longer
        one short: calls in flight answer after it, and a minute of no deployment left overwrote the ten minutes of a
        route that cannot chat, its reason too (D98)."""
        with self._state:
            now = self._clock()
            until = self._own_key_until if own_key else self._open_until
            changed = now + seconds > until  # closed, waiting for its probe, or a shorter stop
            if changed and own_key:
                self._own_key_until, self._own_key_suspension = now + seconds, reason
            elif changed:
                self._open_until, self._suspension = now + seconds, reason
            if own_key:  # each stop ends its own probe; an outage's runs on (review of 2026-10-17)
                self._own_key_probing = False
            else:
                self._probing = False
        if changed:
            log.warning("b-api calls held back for %.0f s: %s (%s)", seconds, reason, cause)

    def _close(self) -> None:
        """The b-api answered: the breaker closes and the failures in a row start again at zero. An answer to the key
        of a request says nothing of the service's own: a stop on that one keeps its ten minutes (audit 2026-10-15)."""
        own_key = request_key() is None
        with self._state:
            resumed = self._open_until != 0.0 or (own_key and self._own_key_until != 0.0)
            self._open_until, self._probing, self._failures = 0.0, False, 0
            if own_key:
                self._own_key_until, self._own_key_probing = 0.0, False
        if resumed:
            log.info("b-api answers again; the calls resume")

    def _key_header(self) -> dict[str, str]:
        """The one header that carries the key of a call (D105): the request's as it came, else the service's own."""
        key = request_key()
        return {key.header: key.value} if key is not None else {X_API_KEY: self._key}

    def _redact(self, text: str) -> str:
        """``text`` without the keys of this call: the service's own and the request's, with and without its scheme. An
        empty key is none: replaced, it put three stars between every two signs."""
        key = request_key()
        secrets = [self._key, *((key.value, key.value.split()[-1]) if key is not None else ())]
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            text = text.replace(secret, "***")
        return text


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
