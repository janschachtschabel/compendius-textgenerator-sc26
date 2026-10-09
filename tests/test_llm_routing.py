"""b-api routing (D97): the router of the b-api as a provider - a route name in the field ``model`` at
``/api/v1/llm/router/``, the request parameters of the model family ``B_API_MODEL`` names, the router's own errors.

Measured on staging on 2026-10-09 with a route of our own (``kompendium-test``: gpt-6-luna, reserve gpt-5.6-luna): a
route answers like a model; an unknown route is a 400 "No route configured for model 'x'", a model without a price a
503 "Model pricing unavailable", a route without an active deployment a 503 "No deployment could serve model 'x' (no
deployment left)", each within 0.15 s; a model of another parameter family answers with the provider's 400, marked
``X-Error-Source: upstream``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.compendium.gateway import LlmGateway, LlmOptions
from app.domain.requests import GenerateRequest
from app.llm.budget import TokenBudget
from app.llm.client import BApiClient, LlmError, LlmHeldBackError
from app.main import create_app
from app.service import CompendiumService
from app.settings import Settings
from app.wiring import build_llm
from tests.conftest import make_settings
from tests.test_llm_client import BASE, KEY, MESSAGES, FakeBApi, client_lines, completion
from tests.test_pipeline_llm import answer_from_evidence

ROUTE = "kompendium-test"
ROUTES = {"object": "list", "data": [{"id": ROUTE, "object": "model", "created": 0, "owned_by": "router"}]}
NO_ROUTE = {"error": f"No route configured for model '{ROUTE}'"}
FAMILY = {
    "error": {
        "message": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' "
        "instead.",
        "type": "invalid_request_error",
        "param": "max_tokens",
        "code": "unsupported_parameter",
    }
}
UPSTREAM = {"X-Error-Source": "upstream", "X-Upstream-Status": "400"}

Answer = tuple[int, Any, dict[str, str]]


class Router:
    """The b-api router: the route list at ``/models``, and each chat call answered with the next of ``answers``,
    then with an answer of ``model``."""

    def __init__(self, *answers: Answer, model: str = "gpt-6-luna") -> None:
        self.answers = list(answers)
        self.model = model
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=ROUTES)
        status, body, headers = self.answers.pop(0) if self.answers else (200, answered_by(self.model), {})
        return httpx.Response(status, json=body, headers=headers)

    @property
    def chats(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path.endswith("/chat/completions")]


def answered_by(model: str) -> dict[str, Any]:
    return {**completion("OK"), "model": model}


def routed(
    transport: Callable[[httpx.Request], httpx.Response], clock: Callable[[], float] | None = None, **kwargs: Any
) -> tuple[BApiClient, list[float]]:
    sleeps: list[float] = []
    options: dict[str, Any] = {"provider": "router", "model": "gpt-6-luna", "route": ROUTE, "timeout_s": 30.0}
    options.update(kwargs)
    if clock is not None:
        options["clock"] = clock
    client = BApiClient(
        BASE,
        KEY,
        transport=httpx.MockTransport(transport),
        sleep=sleeps.append,
        backoff_s=1.5,
        attempts=3,
        jitter=lambda: 0.5,
        **options,
    )
    return client, sleeps


def test_the_router_gets_the_route_as_model_and_the_parameters_of_the_model_family() -> None:
    """A route name says nothing about its models: the parameters follow B_API_MODEL, here a reasoning model."""
    fake = FakeBApi()
    client, _ = routed(fake)

    client.chat(MESSAGES, max_output_tokens=50)

    assert fake.requests[0].url.path == "/api/v1/llm/router/chat/completions"
    body = fake.bodies[0]
    assert body["model"] == ROUTE
    assert body["max_completion_tokens"] == 50 and body["reasoning_effort"] == "low" and body["verbosity"] == "low"
    assert "max_tokens" not in body and "temperature" not in body


def test_without_a_route_the_router_asks_for_the_route_named_like_the_model() -> None:
    """The b-api's way to switch without an outage: a route named like the model the applications send."""
    fake = FakeBApi()
    client, _ = routed(fake, route="")

    client.chat(MESSAGES, max_output_tokens=50)

    assert client.route == "gpt-6-luna" and fake.bodies[0]["model"] == "gpt-6-luna"


def test_the_other_providers_send_the_model_and_leave_a_route_aside() -> None:
    fake = FakeBApi()
    client, _ = routed(fake, provider="openai")

    client.chat(MESSAGES, max_output_tokens=50)

    assert client.route == "" and fake.bodies[0]["model"] == "gpt-6-luna"
    assert fake.requests[0].url.path == "/api/v1/llm/openai/chat/completions"


def test_the_model_check_looks_for_the_route_in_the_list_of_the_router() -> None:
    found = routed(Router())[0].check_model()
    assert found.ok and found.found and found.model == ROUTE
    assert ROUTE in found.message and "gpt-6-luna" in found.message

    missing = routed(Router(), route="kompendium-fehlt")[0].check_model()
    assert not missing.ok and not missing.found
    assert "kompendium-fehlt" in missing.message and "B_API_ROUTE" in missing.message

    router = Router()
    pattern = routed(router, route="openai/gpt-6-luna")[0].check_model()
    assert pattern.ok and not pattern.found, "provider/model reaches the provider without a route, never listed"
    assert "ohne Route" in pattern.message
    assert router.requests[0].url.path == "/api/v1/llm/router/models"


def test_a_missing_route_holds_the_calls_back_ten_minutes_and_names_the_route(caplog: pytest.LogCaptureFixture) -> None:
    """A route deleted or switched off after the start answers every call with this 400; no call fixes it."""
    router = Router((400, NO_ROUTE, {}))
    client, sleeps = routed(router)

    with caplog.at_level(logging.INFO, logger="app.llm.client"):
        with pytest.raises(LlmError, match=ROUTE) as failure:
            client.chat(MESSAGES, max_output_tokens=10)
        with pytest.raises(LlmHeldBackError, match=ROUTE):
            client.chat(MESSAGES, max_output_tokens=10)

    assert failure.value.status == 400 and len(router.chats) == 1 and sleeps == []
    [opened] = [line for line in client_lines(caplog) if "held back" in line]
    assert "600 s" in opened and "B_API_ROUTE" in opened


@pytest.mark.parametrize(
    ("message", "seconds", "says"),
    [
        ("Model pricing unavailable for 'gpt-6-lunaa' - cannot enforce cost quota", 600, "Preis"),
        (f"No deployment could serve model '{ROUTE}' (attempts: luna-6:NOT_ELIGIBLE (HTTP 403))", 600, "Chat"),
        (f"No deployment could serve model '{ROUTE}' (no deployment left)", 60, "kein Modell"),
    ],
)
def test_a_503_the_router_cannot_mend_is_not_retried(message: str, seconds: int, says: str) -> None:
    """The router has tried its deployments before it answers so (b-api test of 2026-10-01: a retry waited 15 s for
    the same answer); a model without a price or one that cannot chat stays so, no deployment left may pass."""
    now = [1000.0]
    router = Router((503, {"error": message}, {}))
    client, sleeps = routed(router, clock=lambda: now[0])

    with pytest.raises(LlmError, match=says) as failure:
        client.chat(MESSAGES, max_output_tokens=10)

    assert failure.value.status == 503 and len(router.chats) == 1 and sleeps == []
    now[0] += seconds - 1
    assert client.suspended
    now[0] += 2
    assert not client.suspended


def test_any_other_503_of_the_router_is_retried_as_before() -> None:
    router = Router((503, {"error": "Service temporarily unavailable"}, {}))
    client, sleeps = routed(router)

    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"
    assert len(router.chats) == 2 and sleeps == [1.5]


def test_a_route_of_another_model_family_is_named_in_the_warning(caplog: pytest.LogCaptureFixture) -> None:
    """A route may bundle only models that take the same parameters; one switched to another family refuses every
    call with the provider's 400. The calls go on: another question may pass."""
    router = Router((400, FAMILY, UPSTREAM))
    client, _ = routed(router)

    with caplog.at_level(logging.WARNING, logger="app.llm.client"):
        with pytest.raises(LlmError):
            client.chat(MESSAGES, max_output_tokens=10)

    [warning] = client_lines(caplog)
    assert "B_API_MODEL" in warning and "gpt-6-luna" in warning and ROUTE in warning
    assert not client.suspended and client.chat(MESSAGES, max_output_tokens=10).text == "OK"


def test_the_router_says_once_which_model_answers(caplog: pytest.LogCaptureFixture) -> None:
    """The answer names only the model, not the deployment; a new one in the log shows the route turned to its
    reserve."""
    router = Router((200, answered_by("gpt-6-luna"), {}), (200, answered_by("gpt-6-luna"), {}), model="gpt-5.6-luna")
    client, _ = routed(router)

    with caplog.at_level(logging.INFO, logger="app.llm.client"):
        for _ in range(3):
            client.chat(MESSAGES, max_output_tokens=10)

    lines = [line for line in client_lines(caplog) if "answers with" in line]
    assert lines == [
        f"b-api routing: route {ROUTE!r} answers with gpt-6-luna",
        f"b-api routing: route {ROUTE!r} answers with gpt-5.6-luna",
    ]


def test_a_model_answering_without_a_route_writes_no_such_line(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = routed(FakeBApi(), provider="openai")

    with caplog.at_level(logging.INFO, logger="app.llm.client"):
        client.chat(MESSAGES, max_output_tokens=10)

    assert not [line for line in client_lines(caplog) if "answers with" in line]


@pytest.mark.parametrize(
    ("provider", "route", "sent"),
    [("router", "", "gpt-6-luna"), ("router", ROUTE, ROUTE), ("openai", ROUTE, ""), ("academiccloud", "", "")],
)
def test_the_settings_name_the_route_the_router_gets(provider: str, route: str, sent: str) -> None:
    settings = Settings(_env_file=None, b_api_provider=provider, b_api_route=route)
    assert settings.b_api_route_name == sent


def test_the_gateway_asks_the_router_for_the_configured_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    router = Router()

    def offline_client(*args: Any, **kwargs: Any) -> BApiClient:
        return BApiClient(*args, transport=httpx.MockTransport(router), **kwargs)

    monkeypatch.setattr("app.wiring.BApiClient", offline_client)
    settings = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", b_api_provider="router", b_api_route=ROUTE)

    gateway = build_llm(settings)

    assert gateway is not None and gateway.client.route == ROUTE and gateway.client.model == "gpt-6-luna"
    assert gateway.check is not None and gateway.check.ok
    assert router.requests[0].url.path == "/api/v1/llm/router/models"
    assert gateway.client.max_concurrency == 20, "the routes of the service bundle OpenAI models"


def test_a_route_without_the_router_is_named_at_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "app.wiring.BApiClient",
        lambda *args, **kwargs: BApiClient(*args, transport=httpx.MockTransport(FakeBApi()), **kwargs),
    )
    settings = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", b_api_route=ROUTE)

    with caplog.at_level(logging.WARNING):
        gateway = build_llm(settings)

    assert gateway is not None and gateway.client.route == ""
    assert "B_API_ROUTE" in caplog.text and "B_API_PROVIDER=router" in caplog.text


def routed_gateway(transport: Callable[[httpx.Request], httpx.Response]) -> LlmGateway:
    client = BApiClient(
        BASE, KEY, provider="router", model="gpt-6-luna", route=ROUTE, transport=httpx.MockTransport(transport)
    )
    return LlmGateway(
        client, TokenBudget(per_request=20_000, daily=0), LlmOptions(fast_sections=("sc26_1",), concurrency=2)
    )


def test_health_names_the_route(settings: Settings) -> None:
    app = create_app(settings)
    app.state.llm = routed_gateway(Router())
    app.state.llm.check_model()

    with TestClient(app) as client:
        llm = client.get("/health").json()["components"]["llm"]

    assert llm["provider"] == "router" and llm["route"] == ROUTE and llm["model"] == "gpt-6-luna"
    assert llm["available"] and llm["check"]["model"] == ROUTE and llm["reason"] is None


def test_the_compendium_names_the_route_beside_the_model_that_answered(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "llm", routed_gateway(FakeBApi(answer_from_evidence, models=ROUTES)))

    result = service.generate(GenerateRequest(topic="Optik", generation="llm-fast", parts=["world"]))

    llm = result.frontmatter["llm"]
    assert llm["provider"] == "router" and llm["route"] == ROUTE
    assert llm["model"] == "gpt-5.6-luna", "the model that answered, as the router's answer names it"


# Review of 2026-10-09 (D98). The causes in a list of attempts follow the b-api's doc, "attempts: <deployment>:<cause>
# (HTTP <status>)"; only NOT_ELIGIBLE was named there, the other causes are assumed.
LISTED = "No deployment could serve model '" + ROUTE + "' (attempts: {})"


@pytest.mark.parametrize(
    "attempts",
    [
        "luna-6:UPSTREAM_ERROR (HTTP 500), luna-5-6-reserve:RATE_LIMITED (HTTP 429)",
        "luna-6:UPSTREAM_ERROR (HTTP 500), luna-5-6-reserve:NOT_ELIGIBLE (HTTP 403)",
    ],
)
def test_a_503_whose_attempts_may_pass_is_retried(attempts: str) -> None:
    """An answer listing attempts that failed for a while - a 429 or 5xx of the provider - took a 60 s stop of every
    call, a list with one model that cannot chat ten minutes; through openai the same failure was retried."""
    router = Router((503, {"error": LISTED.format(attempts)}, {}))
    client, sleeps = routed(router)

    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"
    assert len(router.chats) == 2 and sleeps == [1.5] and not client.suspended


@pytest.mark.parametrize("longer_first", [True, False])
def test_a_shorter_stop_never_cuts_a_longer_one_short(caplog: pytest.LogCaptureFixture, longer_first: bool) -> None:
    """With calls in flight a 60 s stop overwrote the ten minutes another answer had set, and its reason, without a
    line; a longer stop after a shorter one replaces it and says so."""
    long_stop: Answer = (503, {"error": LISTED.format("luna-6:NOT_ELIGIBLE (HTTP 403)")}, {})
    short_stop: Answer = (503, {"error": f"No deployment could serve model '{ROUTE}' (no deployment left)"}, {})
    answers = [long_stop, short_stop] if longer_first else [short_stop, long_stop]
    both_sent, first_back = threading.Barrier(2), threading.Event()
    taken: dict[int, int] = {}
    lock = threading.Lock()

    def transport(request: httpx.Request) -> httpx.Response:
        both_sent.wait(timeout=5)  # both calls are out before either answer comes back
        with lock:
            index = taken[threading.get_ident()] = len(taken)
        if index == 1:
            first_back.wait(timeout=5)  # the second answer arrives after the first one's stop
        status, body, headers = answers[index]
        return httpx.Response(status, json=body, headers=headers)

    now = [1000.0]
    client, _ = routed(transport, clock=lambda: now[0])
    outcomes: list[str] = []

    def call() -> None:
        try:
            client.chat(MESSAGES, max_output_tokens=10)
            outcomes.append("answered")
        except LlmError as exc:
            outcomes.append(type(exc).__name__)
        finally:
            if taken.get(threading.get_ident()) == 0:
                first_back.set()

    with caplog.at_level(logging.WARNING, logger="app.llm.client"):
        threads = [threading.Thread(target=call) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert outcomes == ["LlmError", "LlmError"]
    assert "Chat" in client.suspension_reason
    held = [line for line in client_lines(caplog) if "held back" in line]
    assert held[-1].startswith("b-api calls held back for 600 s")
    assert len(held) == (1 if longer_first else 2)
    now[0] += 599
    assert client.suspended, "the ten minutes of the longer stop hold"
    now[0] += 2
    assert not client.suspended


def test_after_a_route_stop_one_call_probes_and_stops_again_or_resumes(caplog: pytest.LogCaptureFixture) -> None:
    now = [1000.0]
    router = Router((400, NO_ROUTE, {}), (400, NO_ROUTE, {}))
    client, _ = routed(router, clock=lambda: now[0])

    with caplog.at_level(logging.INFO, logger="app.llm.client"):
        with pytest.raises(LlmError):
            client.chat(MESSAGES, max_output_tokens=10)
        now[0] += 601
        with pytest.raises(LlmError, match=ROUTE):
            client.chat(MESSAGES, max_output_tokens=10)  # the probe meets the same answer
        assert client.suspended and len(router.chats) == 2
        now[0] += 601
        assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"  # the route is back

    assert "b-api answers again; the calls resume" in client_lines(caplog)
    assert not client.suspended


def test_the_family_of_a_model_named_with_its_provider_is_the_models() -> None:
    """B_API_MODEL=openai/gpt-6-luna sent max_tokens and temperature to gpt-6-luna, which refuses both."""
    fake = FakeBApi()
    client, _ = routed(fake, model="openai/gpt-6-luna", route="")

    client.chat(MESSAGES, max_output_tokens=50)

    body = fake.bodies[0]
    assert body["model"] == "openai/gpt-6-luna" and body["max_completion_tokens"] == 50
    assert "max_tokens" not in body and "temperature" not in body


@pytest.mark.parametrize(("route", "warned"), [("openai/gpt-4.1-mini", True), ("openai/gpt-5.6-luna", False)])
def test_a_route_naming_a_model_of_another_family_is_named_at_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, route: str, warned: bool
) -> None:
    """provider/model names its model: one of another family than B_API_MODEL refuses every call with a 400."""
    monkeypatch.setattr(
        "app.wiring.BApiClient",
        lambda *args, **kwargs: BApiClient(*args, transport=httpx.MockTransport(Router()), **kwargs),
    )
    settings = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", b_api_provider="router", b_api_route=route)

    with caplog.at_level(logging.WARNING):
        build_llm(settings)

    assert (route in caplog.text and "B_API_MODEL" in caplog.text) is warned


def test_health_names_the_route_while_the_llm_is_off(tmp_path: Path) -> None:
    settings = make_settings([], tmp_path, zim_dir=tmp_path, b_api_provider="router", b_api_route=ROUTE)

    with TestClient(create_app(settings)) as client:
        llm = client.get("/health").json()["components"]["llm"]

    assert llm["enabled"] is False and llm["provider"] == "router" and llm["route"] == ROUTE


def test_the_start_line_names_the_route_and_the_family(
    sample_zims: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "app.wiring.BApiClient",
        lambda *args, **kwargs: BApiClient(*args, transport=httpx.MockTransport(Router()), **kwargs),
    )
    settings = make_settings(
        sample_zims.values(),
        tmp_path / "state",
        llm_enabled=True,
        b_api_key="k",
        b_api_provider="router",
        b_api_route=ROUTE,
    )

    with caplog.at_level(logging.INFO, logger="app.main"):
        create_app(settings).state.service.close()

    [line] = [record.getMessage() for record in caplog.records if record.getMessage().startswith("Kompendium-API ")]
    assert f"LLM router {ROUTE} (parameters of gpt-6-luna)" in line


def test_health_names_why_the_router_stopped_the_calls(settings: Settings) -> None:
    """After a stop at runtime /health said available false beside a check that found the route, without a reason."""
    app = create_app(settings)
    gateway = routed_gateway(Router((400, NO_ROUTE, {})))
    gateway.check_model()
    app.state.llm = gateway
    with pytest.raises(LlmError):
        gateway.client.chat(MESSAGES, max_output_tokens=10)

    with TestClient(app) as client:
        llm = client.get("/health").json()["components"]["llm"]

    assert llm["available"] is False and llm["check"]["ok"], "the check at the start found the route"
    assert ROUTE in llm["reason"] and "B_API_ROUTE" in llm["reason"]


def test_a_b_api_without_the_router_says_so() -> None:
    """A b-api that has no routing yet answers 404: the check said "b-api nicht erreichbar", the stop "Schlüssel,
    Berechtigung oder Modell prüfen"."""
    client, _ = routed(lambda request: httpx.Response(404, json={"error": "Not Found"}))

    check = client.check_model()

    assert not check.ok and "Routing" in check.message and "404" in check.message
    assert client.suspended and "Routing" in client.suspension_reason


def test_the_name_of_an_answering_model_stays_on_one_line_and_the_names_are_bounded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The field model comes from upstream: a line break forged a record of the text log, and every new name stayed
    in memory for the life of the worker."""
    names = ["gpt-6-luna\nFAKE: a forged line", *(f"modell-{number}" for number in range(40))]
    router = Router(*((200, answered_by(name), {}) for name in names))
    client, _ = routed(router)

    with caplog.at_level(logging.INFO, logger="app.llm.client"):
        for _ in names:
            client.chat(MESSAGES, max_output_tokens=10)

    lines = [line for line in client_lines(caplog) if "answers with" in line]
    assert lines[0] == f"b-api routing: route {ROUTE!r} answers with gpt-6-luna FAKE: a forged line"
    assert len(lines) == 32


def test_a_refused_value_gets_no_hint_on_the_family(caplog: pytest.LogCaptureFixture) -> None:
    """unsupported_value is also OpenAI's answer to an effort or verbosity the model lacks, within the right family."""
    value = {
        "error": {
            "message": "Unsupported value: 'reasoning_effort' does not support 'none' with this model.",
            "type": "invalid_request_error",
            "param": "reasoning_effort",
            "code": "unsupported_value",
        }
    }
    client, _ = routed(Router((400, value, UPSTREAM)))

    with caplog.at_level(logging.WARNING, logger="app.llm.client"):
        with pytest.raises(LlmError):
            client.chat(MESSAGES, max_output_tokens=10)

    [warning] = client_lines(caplog)
    assert "B_API_MODEL" not in warning
