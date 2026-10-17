"""Which calls a stop of the b-api client holds back (review of 2026-10-17): a limit or a 404 of the service's own key
holds back the calls with that key only, the callers' own keys keep the LLM (D106); the probe after a break decides for
its kind of stop alone; a request is told the stop that holds it back."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from app.compendium.gateway import LlmGateway, LlmOptions
from app.llm.budget import TokenBudget
from app.llm.client import BApiClient, LlmError, LlmHeldBackError, LlmKeyRefusedError
from app.llm.credentials import RequestKey, use_request_key
from tests.test_llm_client import BASE, KEY, MESSAGES, OPENAI_MODELS, completion

CALLER = "Bearer caller-key-0123456789abcdef"
Answer = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def no_request_key() -> Iterator[None]:
    use_request_key(None)
    yield
    use_request_key(None)


def by_key(own: Answer, caller: Answer) -> httpx.MockTransport:
    """A b-api answering the service's own key (X-API-Key) and a caller's (Authorization) each its own way."""
    return httpx.MockTransport(lambda request: caller(request) if "authorization" in request.headers else own(request))


def ok(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json=OPENAI_MODELS)
    return httpx.Response(200, json=completion("OK"))


def status(code: int, **headers: str) -> Answer:
    return lambda request: httpx.Response(code, json={"error": {"message": f"status {code}"}}, headers=headers)


def client_of(transport: httpx.MockTransport, now: list[float], **options: Any) -> BApiClient:
    settings: dict[str, Any] = {"provider": "openai", "model": "gpt-5.6-luna", "attempts": 3, "backoff_s": 0.0}
    settings.update(options)
    return BApiClient(BASE, KEY, transport=transport, sleep=lambda s: None, clock=lambda: now[0], **settings)


def held_back(client: BApiClient) -> bool:
    """Read anew each time: the stop changes with the calls and the key of the request."""
    return client.suspended


def as_caller() -> RequestKey:
    key = RequestKey("Authorization", CALLER)
    use_request_key(key)
    return key


def test_a_limit_of_the_service_s_own_key_leaves_the_callers_their_llm() -> None:
    """Three 429s to the service's key counted as an outage: one minute without the LLM for every caller (#1)."""
    now = [0.0]
    client = client_of(by_key(own=status(429), caller=ok), now)

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert held_back(client) and "429" in client.suspension_reason
    as_caller()
    assert not held_back(client)
    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"


def test_a_404_to_the_service_s_own_key_leaves_the_callers_their_llm() -> None:
    """The mirror of C10: a 404 to the service's key held back every caller for ten minutes (#3)."""
    now = [0.0]
    client = client_of(by_key(own=status(404), caller=ok), now)

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert held_back(client)
    as_caller()
    assert not held_back(client)


def test_a_404_the_provider_sent_behind_a_route_is_no_missing_router() -> None:
    """The b-api passes the provider's errors on with X-Error-Source: upstream; a model the route lost read as "die
    b-api kennt kein Routing" and stopped every caller (#3)."""
    now = [0.0]
    upstream = status(404, **{"X-Error-Source": "upstream"})
    client = client_of(by_key(own=upstream, caller=ok), now, provider="router", route="kompendium")

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert held_back(client) and "kein Routing" not in client.suspension_reason
    as_caller()
    assert not held_back(client)


def test_a_404_of_the_b_api_itself_behind_a_route_still_stops_every_call() -> None:
    """Without the router the b-api answers every key the same: that stop stays for all (D98)."""
    now = [0.0]
    client = client_of(by_key(own=status(404), caller=ok), now, provider="router", route="kompendium")

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    as_caller()
    assert held_back(client) and "kein Routing" in client.suspension_reason


def test_a_caller_s_call_that_probes_after_an_outage_does_not_lose_its_key_to_one_429() -> None:
    """The probe has one attempt; one passing 429 marked the caller's key as at its limit for its whole request (#7)."""
    now = [0.0]
    answers = iter([503, 503, 503, 429])

    def caller(request: httpx.Request) -> httpx.Response:
        return status(next(answers))(request)

    client = client_of(by_key(own=ok, caller=caller), now)
    key = as_caller()
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)  # three 503: an outage, a minute for every key
    now[0] = 61.0

    with pytest.raises(LlmError) as raised:
        client.chat(MESSAGES, max_output_tokens=10)  # the probe meets a 429

    assert not isinstance(raised.value, LlmKeyRefusedError) and key.refused is None


def test_an_outage_does_not_free_the_probe_of_the_service_s_own_key() -> None:
    """Every stop cleared both probe flags: an outage met by a caller let a second call of the service's key go out
    while the first still probed whether the key works again (#6)."""
    now = [0.0]
    in_probe, release = threading.Event(), threading.Event()
    own_answers = iter([403])

    def own(request: httpx.Request) -> httpx.Response:
        code = next(own_answers, None)
        if code is not None:
            return status(code)(request)
        in_probe.set()
        release.wait(5)
        return ok(request)

    client = client_of(by_key(own=own, caller=status(503)), now)
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)  # 403: ten minutes for the service's key
    now[0] = 601.0
    probe = threading.Thread(target=lambda: client.chat(MESSAGES, max_output_tokens=10))
    probe.start()
    assert in_probe.wait(5)

    def caller_meets_an_outage() -> None:
        use_request_key(RequestKey("Authorization", CALLER))
        with pytest.raises(LlmError):
            client.chat(MESSAGES, max_output_tokens=10)

    outage = threading.Thread(target=caller_meets_an_outage)
    outage.start()
    outage.join(5)
    now[0] = 700.0  # past the outage's minute; the probe of the service's key still runs
    try:
        with pytest.raises(LlmHeldBackError):
            client.chat(MESSAGES, max_output_tokens=10)
    finally:
        release.set()
        probe.join(5)


def test_a_caller_is_told_the_stop_that_holds_it_back_not_the_check_of_the_service_s_key() -> None:
    """The model check made with the service's key failed with 403; an outage a caller met then read as that 403 in
    its audit and frontmatter (#5)."""
    now = [0.0]

    def own(request: httpx.Request) -> httpx.Response:
        return status(403)(request) if request.url.path.endswith("/models") else ok(request)

    client = client_of(by_key(own=own, caller=status(503)), now)
    gateway = LlmGateway(client, TokenBudget(per_request=20_000), LlmOptions())
    gateway.check_model()
    as_caller()
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert not gateway.available
    assert gateway.unavailable_reason == client.suspension_reason and "403" not in gateway.unavailable_reason


def test_a_route_text_without_a_route_does_not_refuse_the_caller_s_key() -> None:
    """Only a route can be missing: without one a 400 that merely reads like it refused the key of the request (#19)."""
    now = [0.0]
    no_route = status(400)

    def caller(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "No route configured for model 'gpt-5.6-luna'"})

    client = client_of(by_key(own=no_route, caller=caller), now)
    key = as_caller()

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert key.refused is None


def test_a_429_met_by_the_probe_after_an_outage_does_not_reopen_it_for_every_key() -> None:
    """The failures in a row stayed counted through the stop: a probe that met a 429 tripped the outage again for every
    caller, a minute at a time (review of the fixes, 2026-10-17)."""
    now = [0.0]
    answers = iter([503, 503, 503, 429])
    client = client_of(by_key(own=ok, caller=lambda request: status(next(answers, 200))(request)), now)
    as_caller()
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)  # an outage
    now[0] = 61.0

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)  # the probe meets a 429: the b-api answers

    assert not held_back(client)
    use_request_key(None)
    assert not held_back(client)


def test_the_service_s_own_key_still_limited_at_its_probe_stops_that_key_only() -> None:
    now = [0.0]
    client = client_of(by_key(own=status(429), caller=ok), now)
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)  # three 429: a minute for the service's key
    now[0] = 61.0

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)  # its probe: still 429

    assert held_back(client) and "429" in client.suspension_reason
    as_caller()
    assert not held_back(client)


@pytest.mark.parametrize("retry_after", [None, "120"])
def test_a_single_429_does_not_stop_the_service_s_own_key(retry_after: str | None) -> None:
    """The model check asks once, and a Retry-After past the call's time ends the attempts early: one 429 then stopped
    the service's key for a minute (review of the fixes, 2026-10-17)."""
    now = [0.0]
    headers = {"Retry-After": retry_after} if retry_after else {}
    client = client_of(by_key(own=status(429, **headers), caller=ok), now)

    if retry_after:
        with pytest.raises(LlmError):
            client.chat(MESSAGES, max_output_tokens=10, timeout_s=30)
    else:
        client.check_model()

    assert not held_back(client)


def test_a_caller_at_its_limit_is_told_so_while_another_call_probes() -> None:
    """Whether some call probed decided it, not whether this call was the probe: a caller whose three attempts met 429
    kept its key while another call probed after an outage (review of the fixes, 2026-10-17)."""
    now = [0.0]
    limited, failing, probing = (f"Bearer {name}-key-0123456789abcdef" for name in ("limited", "failing", "probing"))
    asleep, wake, in_probe, release = (threading.Event() for _ in range(4))

    def caller(request: httpx.Request) -> httpx.Response:
        key = request.headers["authorization"]
        if key == limited:
            return status(429)(request)
        if key == failing:
            return status(503)(request)
        in_probe.set()
        release.wait(5)
        return ok(request)

    def sleep(seconds: float) -> None:
        if threading.current_thread().name == "limited" and not asleep.is_set():
            asleep.set()
            wake.wait(5)

    client = BApiClient(
        BASE, KEY, provider="openai", model="gpt-5.6-luna", attempts=3, backoff_s=0.0, sleep=sleep,
        clock=lambda: now[0], transport=by_key(own=ok, caller=caller),
    )  # fmt: skip
    seen: list[BaseException] = []
    limited_key = RequestKey("Authorization", limited)

    def run(key: RequestKey) -> None:
        use_request_key(key)
        try:
            client.chat(MESSAGES, max_output_tokens=10)
        except LlmError as exc:
            seen.append(exc)

    first = threading.Thread(target=run, args=(limited_key,), name="limited")
    first.start()
    assert asleep.wait(5)  # its first 429 met, before any stop
    run(RequestKey("Authorization", failing))  # three 503: an outage
    now[0] = 61.0
    probe = threading.Thread(target=run, args=(RequestKey("Authorization", probing),))
    probe.start()
    assert in_probe.wait(5)
    wake.set()
    first.join(5)
    release.set()
    probe.join(5)

    assert limited_key.refused is not None and "429" in limited_key.refused


def test_health_read_with_a_caller_s_key_names_the_failed_check() -> None:
    """/health read by a request with a key of its own said "Modellprüfung steht aus" beside a failed check."""
    now = [0.0]

    def own(request: httpx.Request) -> httpx.Response:
        return status(403)(request) if request.url.path.endswith("/models") else ok(request)

    gateway = LlmGateway(client_of(by_key(own=own, caller=ok), now), TokenBudget(per_request=20_000), LlmOptions())
    gateway.check_model()
    as_caller()

    assert "403" in str(gateway.status()["reason"])
