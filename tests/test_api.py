import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anyio
import anyio.to_thread
import httpx
import pytest
from fastapi.testclient import TestClient

import app.api.health as health_module
from app.llm.client import BApiClient
from app.main import build_llm, create_app
from app.settings import Settings
from tests.conftest import make_settings
from tests.test_lehrplan_api import write_cache
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health_and_ready(client: TestClient) -> None:
    health = client.get("/health").json()
    assert health["status"] == "healthy"
    assert health["service"] == "compendious-text-fastapi"
    assert len(health["components"]["zim"]["archives"]) == 2
    assert health["components"]["llm"] == {
        "enabled": False,
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "available": False,
    }
    assert client.get("/ready").status_code == 200


def test_ready_is_503_without_required_archives(tmp_path: Path) -> None:
    empty_settings = make_settings([], tmp_path, zim_dir=tmp_path)
    with TestClient(create_app(empty_settings)) as client:
        assert client.get("/ready").status_code == 503
        assert client.post("/api/v2/compendium", json={"topic": "Optik"}).status_code == 503


def test_generate_via_api(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", json={"topic": "Optik", "target_length": 8000})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["topic"] == "Optik"
    assert body["markdown"].startswith("---")
    assert body["frontmatter"]["template"] == {"id": "sc26", "version": 1}
    assert body["audit"]["matcher"] == "hybrid_light"


def test_unknown_topic_is_404_with_resolution(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", json={"topic": "Xyzzyplomb"})
    assert response.status_code == 404
    assert response.json()["detail"]["resolution"]["normalized"] == "Xyzzyplomb"


def test_templates_and_strategies(client: TestClient) -> None:
    templates = client.get("/api/v2/templates").json()
    assert {t["id"] for t in templates} >= {"sc26", "standard"}
    assert client.get("/api/v2/templates/sc26").json()["slots"][0]["slot"] == "themendefinition"
    assert client.get("/api/v2/templates/nope").status_code == 404
    strategies = client.get("/api/v2/matching/strategies").json()
    assert any(s["id"] == "hybrid_light" and s["recommended"] for s in strategies)
    status = client.get("/api/v2/zim/status").json()
    assert status["missing_required"] == []


def test_llm_request_without_llm_falls_back_and_says_so(client: TestClient) -> None:
    payload = {
        "topic": "Optik",
        "extraction": "llm",
        "generation": "llm-fast",
        "parts": ["world"],
        "target_length": 8000,
    }
    response = client.post("/api/v2/compendium", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generation"] == "rule-based" and body["frontmatter"]["generation_requested"] == "llm-fast"
    assert body["extraction"] == "rule-based" and body["frontmatter"]["extraction_requested"] == "llm"
    assert "konfiguriert" in body["audit"]["llm"]["note"] and body["audit"]["llm_tokens"] is None
    assert client.post("/api/v2/compendium", json={"topic": "Optik", "generation": "turbo"}).status_code == 422
    assert client.post("/api/v2/compendium", json={"topic": "Optik", "extraction": "turbo"}).status_code == 422


def test_the_former_mode_field_is_rejected_with_a_hint(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", json={"topic": "Optik", "mode": "hybrid-fast"})
    assert response.status_code == 422
    assert "extraction" in response.text and "generation" in response.text and "D33" in response.text


def test_health_reports_the_llm_gateway(settings: Settings) -> None:
    app = create_app(settings)
    app.state.llm = make_gateway(FakeBApi())
    app.state.llm.check_model()
    with TestClient(app) as client:
        llm = client.get("/health").json()["components"]["llm"]
    assert llm["enabled"] and llm["available"] and llm["check"]["ok"]
    assert llm["provider"] == "openai" and llm["model"] == "gpt-5.6-luna" and llm["budget"]["used_today"] == 0


def test_build_llm_needs_the_switch_and_a_key_and_checks_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert build_llm(make_settings([], tmp_path, llm_enabled=False, b_api_key="k")) is None
    assert build_llm(make_settings([], tmp_path, llm_enabled=True, b_api_key="")) is None

    fake = FakeBApi()

    def offline_client(*args: Any, **kwargs: Any) -> BApiClient:
        return BApiClient(*args, transport=httpx.MockTransport(fake), **kwargs)

    monkeypatch.setattr("app.main.BApiClient", offline_client)
    settings = make_settings(
        [],
        tmp_path,
        llm_enabled=True,
        b_api_key="k",
        llm_fast_sections="sc26_1",
        llm_extraction_candidates=5,
        llm_unsupported_sentences="mark",
    )
    gateway = build_llm(settings)
    assert gateway is not None and gateway.check is not None and gateway.check.ok
    assert gateway.options.fast_sections == ("sc26_1",) and gateway.options.extraction_candidates == 5
    assert gateway.synthesizer.mark_unsupported is True
    assert (gateway.client.reasoning_effort, gateway.client.verbosity) == ("low", "low")
    assert gateway.budget.per_request == 20_000 and gateway.budget.daily == 2_000_000
    assert (tmp_path / "llm_budget.db").exists(), "the daily counter is shared through STATE_DIR"
    assert fake.requests[0].url.path.endswith("/api/v1/llm/openai/models")


def test_test_settings_never_enable_the_llm_from_the_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With LLM_ENABLED and B_API_KEY in the shell the offline fixtures would build a gateway to the real b-api."""
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("B_API_KEY", "shell-key")
    assert make_settings([], tmp_path).llm_enabled is False
    assert make_settings([], tmp_path, llm_enabled=True).llm_enabled is True


def test_matching_defaults_follow_the_measurement_of_2026_09_18(tmp_path: Path) -> None:
    settings = make_settings([], tmp_path)
    assert settings.policy_confident_score == 0.65 and settings.policy_section_smoothing == 0.5


def test_unknown_matcher_is_a_german_422(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", json={"topic": "Optik", "matcher": "gibtsnicht"})
    assert response.status_code == 422
    assert response.json()["detail"] == "Unbekannte Matching-Strategie: gibtsnicht"


def test_an_unknown_matcher_default_stops_the_start(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    # A typo in MATCHER_DEFAULT is the operator's error; every request would otherwise get a client error (422)
    settings = make_settings(sample_zims.values(), tmp_path, matcher_default="gibtsnicht")
    with pytest.raises(ValueError, match="MATCHER_DEFAULT"):
        create_app(settings)


def test_a_request_whose_parts_this_server_cannot_make_is_503(
    sample_zims: dict[str, Path], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(sample_zims.values(), tmp_path, edu_sharing_base_url="")
    payload = {"topic": "Optik", "collection_id": "9e7ae956-e9df-430f-bace-f3db4b910013", "parts": ["collection"]}
    with TestClient(create_app(settings)) as client, caplog.at_level("WARNING"):
        response = client.post("/api/v2/compendium", json=payload)
    assert response.status_code == 503 and "EDU_SHARING_BASE_URL" in response.json()["detail"]
    # A permanent gap of the configuration, not missing archives: the log tells the operator which one
    assert "compendium request refused" in caplog.text


def test_internal_key_errors_are_not_reported_as_client_errors(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(settings)

    def broken(*_args: object, **_kwargs: object) -> None:
        raise KeyError("sc26_99")

    monkeypatch.setattr(app.state.service, "generate", broken)
    with TestClient(app, raise_server_exceptions=False) as failing:
        assert failing.post("/api/v2/compendium", json={"topic": "Optik"}).status_code == 500


def test_empty_parts_are_rejected(client: TestClient) -> None:
    assert client.post("/api/v2/compendium", json={"topic": "Optik", "parts": []}).status_code == 422


def test_health_reports_every_component(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(sample_zims.values(), tmp_path / "leer"))) as client:
        components = client.get("/health").json()["components"]
    assert components["lehrplan_cache"] == {"available": False, "harvested_at": None}
    assert components["edu_sharing"] == {"enabled": True}
    write_cache(tmp_path / "voll")
    with TestClient(create_app(make_settings(sample_zims.values(), tmp_path / "voll"))) as client:
        cache = client.get("/health").json()["components"]["lehrplan_cache"]
    assert cache == {"available": True, "harvested_at": "2026-09-17T12:00:00+00:00"}


def test_probes_and_metrics_answer_while_every_default_thread_is_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ZIM_DIR mode, as in the image: the archive check runs before every request
    app = create_app(make_settings([], tmp_path / "state", zim_dir=tmp_path / "zim"))
    threads: list[int] = []
    components = health_module._components

    def spy(request: Any) -> Any:
        threads.append(threading.get_ident())
        return components(request)

    monkeypatch.setattr(health_module, "_components", spy)

    async def scenario() -> list[int]:
        # Long compendium requests hold every thread of anyio's default pool (40 per worker)
        limiter = anyio.to_thread.current_default_thread_limiter()
        holders = [object() for _ in range(int(limiter.total_tokens))]
        for holder in holders:
            await limiter.acquire_on_behalf_of(holder)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                with anyio.fail_after(10):
                    return [(await client.get(path)).status_code for path in ("/health", "/ready", "/metrics")]
        finally:
            for holder in holders:
                limiter.release_on_behalf_of(holder)

    assert anyio.run(scenario) == [200, 503, 200]  # no archives in ZIM_DIR: not ready, but answering
    assert threads and threading.get_ident() not in threads  # the probes read SQLite off the event loop


def test_api_docs_can_be_switched_off(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    settings = make_settings(sample_zims.values(), tmp_path / "state", api_docs_enabled=False)
    with TestClient(create_app(settings)) as hidden:
        assert [hidden.get(path).status_code for path in ("/docs", "/redoc", "/openapi.json")] == [404, 404, 404]
        assert hidden.get("/health").status_code == 200


def test_shutdown_closes_the_outbound_http_clients(settings: Settings) -> None:
    app = create_app(settings)
    closed: list[str] = []

    class Client:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            closed.append(self.name)

    app.state.catalog = Client("kiwix")
    app.state.collections = SimpleNamespace(client=Client("edu-sharing"))
    app.state.llm = SimpleNamespace(client=Client("b-api"))
    with TestClient(app):
        assert closed == []
    assert sorted(closed) == ["b-api", "edu-sharing", "kiwix"]
