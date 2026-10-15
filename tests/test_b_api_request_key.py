"""The b-api key of a request (D105) and the refusals of the b-api (D106).

Behind the b-api's proxy the service gets its caller's key in Authorization (or X-API-Key) and sends it back with
every LLM call of that request, exactly one header, unchanged (b-api, measured on staging 2026-10-13). A key the b-api
refuses - a limit reached, the LLM switched off for it - lets the rest of its request run without the LLM, with one
clear line in the log; the service's own key refused holds all calls back, as before.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.compendium.gateway import LlmGateway, LlmOptions
from app.concurrency import map_in_threads
from app.llm.budget import TokenBudget
from app.llm.call import budgeted_chat
from app.llm.client import BApiClient, LlmError, LlmHeldBackError
from app.llm.credentials import (
    MAX_KEY_CHARS,
    RequestKey,
    UnusableKeyError,
    offered_key,
    use_request_key,
)
from app.main import create_app
from app.settings import Settings
from app.wiring import build_llm
from tests.conftest import make_settings
from tests.test_llm_client import BASE, KEY, MESSAGES, FakeBApi, completion, make_client

CALLER = "Bearer caller-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def no_request_key() -> Any:
    """Every test starts outside a request; a key set by one test must not leak into the next."""
    use_request_key(None)
    yield
    use_request_key(None)


def headers(**values: str) -> Headers:
    return Headers({name.replace("_", "-"): value for name, value in values.items()})


# --- What a request brings ---------------------------------------------------------------------------------------


def test_authorization_wins_and_comes_as_it_was_sent() -> None:
    key = offered_key(headers(authorization=CALLER, x_api_key="other-key-0123456789"))
    assert key is not None and (key.header, key.value) == ("Authorization", CALLER)


def test_x_api_key_brings_the_key_when_no_authorization_came() -> None:
    key = offered_key(headers(x_api_key="b-api-key-0123456789"))
    assert key is not None and (key.header, key.value) == ("X-API-KEY", "b-api-key-0123456789")


def test_x_api_key_stays_the_services_own_while_api_keys_are_set() -> None:
    """API_KEYS reads X-API-Key: then it carries the key of this service, never one of the b-api."""
    assert offered_key(headers(x_api_key="service-key-0123456789"), own_x_api_key=True) is None
    key = offered_key(headers(authorization=CALLER, x_api_key="service-key-0123456789"), own_x_api_key=True)
    assert key is not None and key.header == "Authorization"


def test_no_header_or_an_empty_one_brings_no_key() -> None:
    assert offered_key(headers()) is None
    assert offered_key(headers(authorization="", x_api_key="")) is None


@pytest.mark.parametrize(
    "value", ["Bearer " + "k" * MAX_KEY_CHARS, "Bearer schlüssel", " Bearer key", "Bearer key" + chr(127)]
)
def test_a_header_no_request_to_the_b_api_could_carry_is_refused_without_echo(value: str) -> None:
    with pytest.raises(UnusableKeyError) as refused:
        offered_key(headers(authorization=value))
    assert "Authorization" in str(refused.value) and value.strip() not in str(refused.value)


def test_the_key_never_shows_in_its_representation() -> None:
    assert CALLER not in repr(RequestKey("Authorization", CALLER))


# --- What a call sends -------------------------------------------------------------------------------------------


def test_a_call_sends_the_key_of_its_request_and_no_other() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake)
    use_request_key(RequestKey("Authorization", CALLER))

    client.chat(MESSAGES, max_output_tokens=10)

    sent = fake.requests[0].headers
    assert sent["authorization"] == CALLER and "x-api-key" not in sent


def test_an_x_api_key_of_the_request_goes_back_as_x_api_key() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake)
    use_request_key(RequestKey("X-API-KEY", "b-api-key-0123456789"))

    client.chat(MESSAGES, max_output_tokens=10)

    sent = fake.requests[0].headers
    assert sent["x-api-key"] == "b-api-key-0123456789" and "authorization" not in sent


def test_without_a_key_of_the_request_the_services_own_goes() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake)

    client.chat(MESSAGES, max_output_tokens=10)

    sent = fake.requests[0].headers
    assert sent["x-api-key"] == KEY and "authorization" not in sent


def test_without_any_key_no_call_goes_out() -> None:
    fake = FakeBApi()
    client = BApiClient(BASE, "", provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))

    with pytest.raises(LlmHeldBackError, match="Schlüssel"):
        client.chat(MESSAGES, max_output_tokens=10)

    assert fake.requests == []


def test_the_model_check_asks_with_the_services_own_key_only() -> None:
    """Its result holds for every request: a guest's key must not decide it."""
    fake = FakeBApi()
    client, _ = make_client(fake)
    use_request_key(RequestKey("Authorization", CALLER))

    assert client.check_model().ok

    sent = fake.requests[0].headers
    assert sent["x-api-key"] == KEY and "authorization" not in sent


def test_the_parallel_calls_of_a_request_carry_its_key() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake, max_concurrency=4)
    use_request_key(RequestKey("Authorization", CALLER))

    map_in_threads(lambda _: client.chat(MESSAGES, max_output_tokens=10), list(range(6)), workers=4)

    assert [request.headers["authorization"] for request in fake.requests] == [CALLER] * 6


def test_an_error_text_never_carries_the_key_of_the_request() -> None:
    token = CALLER.partition(" ")[2]
    fake = FakeBApi(transport_failures=9, transport_error=httpx.LocalProtocolError(f"bad value {CALLER} {token}"))
    client, _ = make_client(fake)
    use_request_key(RequestKey("Authorization", CALLER))

    with pytest.raises(LlmError) as failed:
        client.chat(MESSAGES, max_output_tokens=10)

    assert token not in str(failed.value) and "LocalProtocolError" in str(failed.value)


def test_a_client_without_a_key_of_its_own_blanks_nothing_else() -> None:
    """Replacing an empty key put three stars between every two signs of a message."""
    fake = FakeBApi(transport_failures=9, transport_error=httpx.ConnectError("refused"))
    client = BApiClient(BASE, "", provider="openai", model="m", transport=httpx.MockTransport(fake), attempts=1)
    use_request_key(RequestKey("Authorization", CALLER))

    with pytest.raises(LlmError) as failed:
        client.chat(MESSAGES, max_output_tokens=10)

    assert "refused" in str(failed.value) and "***" not in str(failed.value)


# --- Refusals (D106) ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 402, 403])
def test_a_refused_key_of_a_request_ends_the_llm_for_that_request_only(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeBApi(statuses=[status])
    client, _ = make_client(fake)
    key = RequestKey("Authorization", CALLER)
    use_request_key(key)

    with caplog.at_level(logging.WARNING, logger="app.llm.client"), pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)
    with pytest.raises(LlmHeldBackError, match=f"HTTP {status}"):
        client.chat(MESSAGES, max_output_tokens=10)  # the rest of the request asks no more

    assert len(fake.bodies) == 1 and key.refused is not None and "Limit" in key.refused
    assert not client.suspended, "another request with another key still gets the LLM"
    [line] = [r.getMessage() for r in caplog.records if "key of this request" in r.getMessage()]
    assert f"HTTP {status}" in line and "llm-free" in line and CALLER not in caplog.text

    use_request_key(None)  # a request without a key of its own: the service's key still answers
    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"


def test_parallel_refusals_of_one_request_write_one_line(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeBApi(statuses=[403] * 6)
    client, _ = make_client(fake, max_concurrency=6)
    use_request_key(RequestKey("Authorization", CALLER))

    def call(_: int) -> str:
        try:
            return client.chat(MESSAGES, max_output_tokens=10).text
        except LlmError as exc:
            return type(exc).__name__

    with caplog.at_level(logging.WARNING, logger="app.llm.client"):
        map_in_threads(call, list(range(6)), workers=6)

    assert len([r for r in caplog.records if "key of this request" in r.getMessage()]) == 1


def test_a_request_key_still_limited_after_its_retries_ends_the_llm_for_its_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """429 is the b-api's answer to more than a key may do; the global breaker stays shut for the other keys."""
    fake = FakeBApi(statuses=[429, 429, 429])
    client, _ = make_client(fake)
    key = RequestKey("Authorization", CALLER)
    use_request_key(key)

    with caplog.at_level(logging.WARNING, logger="app.llm.client"), pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert key.refused is not None and "429" in key.refused
    assert not client.suspended
    assert any("key of this request" in r.getMessage() for r in caplog.records)


def test_the_services_own_key_refused_holds_all_calls_back_and_names_the_limit() -> None:
    client, _ = make_client(FakeBApi(statuses=[402]))

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert client.suspended and "Limit" in client.suspension_reason and "llm-free" in client.suspension_reason


def test_a_route_the_key_of_a_request_lacks_stays_with_that_request() -> None:
    """A route may belong to a key (D97): one the caller's key does not see is no fault of the service's routing."""
    no_route = httpx.Response(400, json={"error": "No route configured for model 'kompendium'"})
    client = BApiClient(
        BASE,
        KEY,
        provider="router",
        model="gpt-6-luna",
        route="kompendium",
        transport=httpx.MockTransport(lambda r: no_route),
    )
    key = RequestKey("Authorization", CALLER)
    use_request_key(key)

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert not client.suspended and key.refused is not None and "kompendium" in key.refused


# --- The gateway and the API -------------------------------------------------------------------------------------


def gateway_of(client: BApiClient) -> LlmGateway:
    return LlmGateway(client, TokenBudget(per_request=20_000), LlmOptions())


def test_a_request_without_any_key_finds_the_llm_unavailable_and_why() -> None:
    gateway = gateway_of(BApiClient(BASE, "", provider="openai", model="m", transport=httpx.MockTransport(FakeBApi())))

    assert not gateway.available and "Schlüssel" in gateway.unavailable_reason
    use_request_key(RequestKey("Authorization", CALLER))
    assert gateway.available, "without a key of its own the service checks no model; the calls decide"


def test_a_refused_request_key_makes_the_llm_unavailable_for_its_request() -> None:
    client, _ = make_client(FakeBApi(statuses=[403]))
    gateway = gateway_of(client)
    gateway.check_model()
    use_request_key(RequestKey("Authorization", CALLER))
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert not gateway.available and "HTTP 403" in gateway.unavailable_reason
    assert gateway.status()["available"], "/health speaks of the service, not of one caller's key"


@pytest.fixture
def b_api(monkeypatch: pytest.MonkeyPatch) -> FakeBApi:
    fake = FakeBApi()

    def offline_client(*args: Any, **kwargs: Any) -> BApiClient:
        return BApiClient(*args, transport=httpx.MockTransport(fake), **kwargs)

    monkeypatch.setattr("app.wiring.BApiClient", offline_client)
    return fake


def request_mode(sample_zims: dict[str, Path], tmp_path: Path, **overrides: Any) -> Settings:
    options: dict[str, Any] = {"llm_enabled": True, "b_api_key_source": "request", "b_api_key": ""}
    options.update(overrides)
    return make_settings(sample_zims.values(), tmp_path / "state", **options)


def test_without_a_key_of_its_own_the_service_builds_its_llm_and_checks_no_model(
    tmp_path: Path, b_api: FakeBApi
) -> None:
    gateway = build_llm(make_settings([], tmp_path, llm_enabled=True, b_api_key_source="request", b_api_key=""))
    assert gateway is not None and gateway.check is None and b_api.requests == []


def test_a_compendium_takes_the_callers_key_to_the_b_api(
    sample_zims: dict[str, Path], tmp_path: Path, b_api: FakeBApi
) -> None:
    with TestClient(create_app(request_mode(sample_zims, tmp_path))) as client:
        answer = client.post(
            "/api/v2/compendium",
            json={"topic": "Optik", "preset": "best-quality-generated"},
            headers={"Authorization": CALLER},
        )
    assert answer.status_code == 200
    chats = [r for r in b_api.requests if r.url.path.endswith("/chat/completions")]
    assert chats and {r.headers["authorization"] for r in chats} == {CALLER}
    assert not any("x-api-key" in r.headers for r in chats)


def test_the_env_mode_keeps_the_callers_authorization_to_itself(
    sample_zims: dict[str, Path], tmp_path: Path, b_api: FakeBApi
) -> None:
    settings = make_settings(sample_zims.values(), tmp_path / "state", llm_enabled=True, b_api_key="service-key-1234")
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/v2/compendium",
            json={"topic": "Optik", "preset": "best-quality-generated"},
            headers={"Authorization": CALLER},
        )
    assert b_api.requests and all("authorization" not in r.headers for r in b_api.requests)
    assert {r.headers["x-api-key"] for r in b_api.requests} == {"service-key-1234"}


def test_a_request_without_any_key_runs_without_the_llm_and_says_why(
    sample_zims: dict[str, Path], tmp_path: Path, b_api: FakeBApi, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING), TestClient(create_app(request_mode(sample_zims, tmp_path))) as client:
        answer = client.post("/api/v2/compendium", json={"topic": "Optik", "preset": "balanced"})
    assert answer.status_code == 200 and b_api.requests == []
    assert "Schlüssel" in str(answer.json()["audit"]["llm"])
    assert any("compendium 'Optik'" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_a_header_no_b_api_could_take_is_a_401(sample_zims: dict[str, Path], tmp_path: Path, b_api: FakeBApi) -> None:
    with TestClient(create_app(request_mode(sample_zims, tmp_path))) as client:
        answer = client.post(
            "/api/v2/compendium", json={"topic": "Optik"}, headers={"Authorization": "Bearer " + "k" * 2000}
        )
    assert answer.status_code == 401 and "Authorization" in answer.json()["detail"]


def test_health_names_where_the_key_comes_from(sample_zims: dict[str, Path], tmp_path: Path, b_api: FakeBApi) -> None:
    with TestClient(create_app(request_mode(sample_zims, tmp_path))) as client:
        llm = client.get("/health").json()["components"]["llm"]
    assert llm["key"] == {"source": "request", "own_key": False} and llm["available"] is True


def test_the_source_defaults_to_the_services_own_key() -> None:
    assert Settings(_env_file=None).b_api_key_source == "env"


@pytest.mark.parametrize(
    ("overrides", "warning"),
    [
        ({"api_keys": "k" * 32}, "X-API-Key stays the service's own key"),
        ({"rate_limit": 30}, "RATE_LIMIT=30"),
    ],
)
def test_the_start_names_what_does_not_fit_a_key_of_the_request(
    tmp_path: Path, b_api: FakeBApi, caplog: pytest.LogCaptureFixture, overrides: dict[str, Any], warning: str
) -> None:
    settings = make_settings([], tmp_path, llm_enabled=True, b_api_key_source="request", **overrides)
    with caplog.at_level(logging.WARNING):
        build_llm(settings)
    assert warning in caplog.text


# --- Review of D105/D106 ------------------------------------------------------------------------------------------


def test_the_services_own_key_refused_leaves_the_callers_their_llm() -> None:
    """The fallback key at its limit must not cut off the callers that bring keys of their own: the b-api limits per
    key (review of 2026-10-14)."""
    client, _ = make_client(FakeBApi(statuses=[403]))
    gateway = gateway_of(client)
    gateway.check_model()
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)
    assert not gateway.available and "Schlüssel des Dienstes" in gateway.unavailable_reason

    use_request_key(RequestKey("Authorization", CALLER))

    assert gateway.available and not client.suspended
    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"


def test_a_callers_answer_does_not_lift_the_stop_on_the_services_own_key() -> None:
    """The caller's key answering says nothing of the service's own: its ten minutes stand (audit 2026-10-15)."""
    client, _ = make_client(FakeBApi(statuses=[403]))
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    use_request_key(RequestKey("Authorization", CALLER))
    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"
    use_request_key(None)

    assert client.suspended and "Schlüssel des Dienstes" in client.suspension_reason


@pytest.mark.parametrize(
    "answer",
    [
        "Model pricing unavailable for 'gpt-6-luna'",
        "No deployment could serve model 'kompendium' (no deployment left)",
    ],
)
def test_a_route_stop_met_with_the_key_of_a_request_stays_with_that_request(answer: str) -> None:
    """A route may belong to a key (D97): what its route answers holds back that request, not every caller's
    (audit 2026-10-15)."""
    client = BApiClient(
        BASE,
        KEY,
        provider="router",
        model="gpt-6-luna",
        route="kompendium",
        transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"error": answer})),
    )
    key = RequestKey("Authorization", CALLER)
    use_request_key(key)

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert key.refused is not None and "kompendium" in key.refused
    use_request_key(None)
    assert not client.suspended


def test_a_route_stop_met_with_the_service_s_own_key_leaves_the_callers_their_llm() -> None:
    """The mirror of a caller's route stop: a route may belong to a key (D97), and the service's own route answering
    "no price" says nothing of the callers' routes; they keep the LLM, key-less calls wait (review of the audit
    2026-10-15)."""
    answer = httpx.Response(503, json={"error": "Model pricing unavailable for 'gpt-6-luna'"})
    client = BApiClient(
        BASE,
        KEY,
        provider="router",
        model="gpt-6-luna",
        route="kompendium",
        transport=httpx.MockTransport(lambda r: answer),
    )
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)
    assert client.suspended

    use_request_key(RequestKey("Authorization", CALLER))

    assert not client.suspended


def test_an_outage_holds_back_the_callers_keys_as_well() -> None:
    client, _ = make_client(FakeBApi(statuses=[503, 503, 503]))
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)
    use_request_key(RequestKey("Authorization", CALLER))
    assert client.suspended


def test_a_refusal_of_the_request_key_is_one_warning_not_one_per_call(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = make_client(FakeBApi(statuses=[403]))
    use_request_key(RequestKey("Authorization", CALLER))
    budget = TokenBudget(per_request=20_000).open_request()

    with caplog.at_level(logging.WARNING):
        budgeted_chat(client, MESSAGES, max_output_tokens=10, budget=budget, what="sc26_1")
        budgeted_chat(client, MESSAGES, max_output_tokens=10, budget=budget, what="sc26_2")

    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


def test_no_cookie_of_one_call_goes_with_the_next() -> None:
    """The client is shared by all requests, which now carry different callers' keys."""
    seen: list[httpx.Request] = []

    def b_api(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=completion("OK"), headers={"Set-Cookie": "session=caller-a; Path=/"})

    client = BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(b_api))
    client.chat(MESSAGES, max_output_tokens=10)
    client.chat(MESSAGES, max_output_tokens=10)

    assert "cookie" not in seen[1].headers


@pytest.mark.parametrize("value", ["a", "Bearer short", "x" * 15])
def test_a_value_too_short_for_a_key_is_refused(value: str) -> None:
    with pytest.raises(UnusableKeyError):
        offered_key(headers(x_api_key=value))


def test_the_token_is_blanked_whatever_the_spaces_before_it() -> None:
    bare = CALLER.partition(" ")[2]
    fake = FakeBApi(transport_failures=9, transport_error=httpx.LocalProtocolError(f"bad {bare}"))
    client, _ = make_client(fake)
    use_request_key(RequestKey("Authorization", "Bearer  " + bare))

    with pytest.raises(LlmError) as failed:
        client.chat(MESSAGES, max_output_tokens=10)

    assert bare not in str(failed.value)


def test_parallel_requests_carry_each_its_own_key(
    sample_zims: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Isolation between requests is the point of D105: every call of a request carries that request's key."""
    calls: list[tuple[str, str]] = []
    lock = threading.Lock()

    def b_api(request: httpx.Request) -> httpx.Response:
        with lock:
            calls.append((request.headers["authorization"], request.content.decode("utf-8")))
        return httpx.Response(200, json=completion("OK"))

    def offline_client(*args: Any, **kwargs: Any) -> BApiClient:
        return BApiClient(*args, transport=httpx.MockTransport(b_api), **kwargs)

    monkeypatch.setattr("app.wiring.BApiClient", offline_client)
    keys = {"Optik": "Bearer key-for-optik-0123456789", "Programmiersprache": "Bearer key-for-programs-0123456789"}
    with TestClient(create_app(request_mode(sample_zims, tmp_path))) as client:

        def ask(topic: str) -> int:
            body = {"topic": topic, "preset": "best-quality-generated", "parts": ["world"]}
            return client.post("/api/v2/compendium", json=body, headers={"Authorization": keys[topic]}).status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(ask, list(keys) * 2)) == [200] * 4

    assert calls
    for key, body in calls:
        topics = [topic for topic in keys if topic in body]
        assert topics in ([], [next(t for t, k in keys.items() if k == key)]), (key, topics)
    assert {key for key, _ in calls} == set(keys.values())
