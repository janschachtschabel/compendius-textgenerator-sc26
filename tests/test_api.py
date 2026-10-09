import base64
import hashlib
import logging
import re
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
from app.main import create_app
from app.settings import Settings
from app.sources.gnd.index import build_gnd_index
from app.sources.wikidata.index import build_index
from app.wiring import build_llm
from tests.conftest import make_settings
from tests.test_gnd_index import write_dumps as write_gnd_dumps
from tests.test_lehrplan_api import write_cache
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway
from tests.test_wikidata_index import write_dumps


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
        "model": "gpt-6-luna",  # the shipped default since D44
        "route": None,  # only the router gets one (D97)
        "available": False,
        "host": "b-api.staging.openeduhub.net",  # derived from the repository, which is staging by default
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


def test_an_llm_switch_without_an_llm_is_a_503_that_names_it(client: TestClient) -> None:
    """D53: a switch that needs an LLM on a server without one is refused, instead of running the rules unasked."""
    payload = {
        "topic": "Optik",
        "extraction": "llm",
        "generation": "llm-fast",
        "parts": ["world"],
        "target_length": 8000,
    }
    response = client.post("/api/v2/compendium", json=payload)
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "LLM_ENABLED" in detail and "extraction=llm" in detail and "generation=llm-fast" in detail
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

    monkeypatch.setattr("app.wiring.BApiClient", offline_client)
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
    assert gateway.client.reasoning_efforts == settings.llm_reasoning_effort_by_prompt
    assert gateway.budget.per_request == 60_000 and gateway.budget.daily == 0  # no daily cap unless set (D67)
    assert (tmp_path / "llm_budget.db").exists(), "the daily counter is shared through STATE_DIR"
    assert fake.requests[0].url.path.endswith("/api/v1/llm/openai/models")


@pytest.fixture
def offline_b_api(monkeypatch: pytest.MonkeyPatch) -> FakeBApi:
    """build_llm with a b-api that answers in the process."""
    fake = FakeBApi()

    def offline_client(*args: Any, **kwargs: Any) -> BApiClient:
        return BApiClient(*args, transport=httpx.MockTransport(fake), **kwargs)

    monkeypatch.setattr("app.wiring.BApiClient", offline_client)
    return fake


@pytest.mark.parametrize(("setting", "allowed"), [({}, False), ({"b_api_response_cache": True}, True)])
def test_the_response_cache_of_the_b_api_stays_off_unless_allowed(
    tmp_path: Path, offline_b_api: FakeBApi, setting: dict[str, Any], allowed: bool
) -> None:
    """D70 (Jan: answers come fresh): without B_API_RESPONSE_CACHE every call names itself anew."""
    gateway = build_llm(make_settings([], tmp_path, llm_enabled=True, b_api_key="k", **setting))
    assert gateway is not None and gateway.client.response_cache is allowed


@pytest.mark.parametrize(
    ("timeout_s", "llm", "warned"), [(5, True, True), (10, True, True), (11, True, False), (5, False, False)]
)
def test_a_deadline_too_short_for_an_llm_call_is_named_at_start(
    tmp_path: Path, offline_b_api: FakeBApi, caplog: pytest.LogCaptureFixture, timeout_s: int, llm: bool, warned: bool
) -> None:
    """A call starts only while five seconds of the request remain: at REQUEST_TIMEOUT_S=5 none started, up to 10
    hardly one, and every LLM step fell back to the rules without a word (audit 2026-09-29, S6)."""
    settings = make_settings([], tmp_path, llm_enabled=llm, b_api_key="k", request_timeout_s=timeout_s)

    with caplog.at_level(logging.WARNING):
        build_llm(settings)

    assert ("REQUEST_TIMEOUT_S" in caplog.text) is warned


@pytest.mark.parametrize(
    ("model", "setting", "value", "warned"),
    [
        ("gpt-6-luna", "llm_reasoning_effort", "lwo", True),
        ("gpt-6-luna", "llm_verbosity", "Low", True),
        ("gpt-6-luna", "llm_reasoning_effort", "minimal", False),
        ("gpt-6-luna", "llm_verbosity", "high", False),
        ("gpt-4.1-mini", "llm_reasoning_effort", "lwo", False),  # a classic model is sent neither
    ],
)
def test_a_reasoning_setting_the_models_do_not_know_is_named_at_start(
    tmp_path: Path,
    offline_b_api: FakeBApi,
    caplog: pytest.LogCaptureFixture,
    model: str,
    setting: str,
    value: str,
    warned: bool,
) -> None:
    """Both settings are sent to a reasoning model as they stand: a typo would likely fail every call with a 400 while
    /health says available. The model may know values the service does not, so it is a warning (audit 2026-09-29,
    S7)."""
    settings = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", b_api_model=model, **{setting: value})

    with caplog.at_level(logging.WARNING):
        build_llm(settings)

    assert (setting.upper() in caplog.text) is warned


def test_the_efforts_per_question_come_from_the_settings(tmp_path: Path, offline_b_api: FakeBApi) -> None:
    """M59: LLM_REASONING_EFFORTS names the questions that think otherwise than LLM_REASONING_EFFORT - shipped: the
    five that answered as well without thinking; empty keeps that list, as every setting does without an entry."""
    named = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", llm_reasoning_efforts="topic_articles = low,")
    shipped = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", llm_reasoning_efforts="")

    gateway = build_llm(named)

    assert gateway is not None and gateway.client.reasoning_efforts == {"topic_articles": "low"}
    assert shipped.llm_reasoning_effort_by_prompt == make_settings([], tmp_path).llm_reasoning_effort_by_prompt
    assert shipped.llm_reasoning_effort_by_prompt == {
        "topic_articles": "none",
        "article_choice": "none",
        "curriculum_check": "none",
        "topic_wording": "none",
        "qa_pairs": "none",
    }


@pytest.mark.parametrize(
    ("value", "warned"),
    [("section_coverage=low", False), ("section_coverag=low", True), ("section_coverage=lwo", True), ("low", True)],
)
def test_an_effort_per_question_the_service_does_not_know_is_named_at_start(
    tmp_path: Path, offline_b_api: FakeBApi, caplog: pytest.LogCaptureFixture, value: str, warned: bool
) -> None:
    """A question the service does not ask would never get its effort, and a typo of the effort would fail its calls
    with a 400: both are named at start."""
    settings = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", llm_reasoning_efforts=value)

    with caplog.at_level(logging.WARNING):
        build_llm(settings)

    assert ("LLM_REASONING_EFFORTS" in caplog.text) is warned


@pytest.mark.parametrize(("daily", "keys", "warned"), [(0, "", True), (0, "k" * 32, False), (2_000_000, "", False)])
def test_an_llm_open_to_anyone_without_a_daily_cap_is_named_at_start(
    tmp_path: Path, offline_b_api: FakeBApi, caplog: pytest.LogCaptureFixture, daily: int, keys: str, warned: bool
) -> None:
    """Without a daily cap (the default since D67) only API_KEYS keeps strangers from spending b-api tokens without
    limit; a server open to all is named at start, as the review page without keys is (audit 2026-09-29, S2)."""
    settings = make_settings([], tmp_path, llm_enabled=True, b_api_key="k", llm_daily_token_budget=daily, api_keys=keys)

    with caplog.at_level(logging.WARNING):
        build_llm(settings)

    assert ("LLM_DAILY_TOKEN_BUDGET" in caplog.text) is warned


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
    assert components["edu_sharing"] == {"enabled": True, "repository": "repository.staging.openeduhub.net"}
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


@pytest.mark.parametrize(
    ("path", "script", "root_path"),
    [
        ("/docs", "swagger-ui-dist@5.33.0/swagger-ui-bundle.js", ""),
        ("/docs", "swagger-ui-dist@5.33.0/swagger-ui-bundle.js", "/kompendium"),  # behind a proxy with a prefix
        ("/redoc", "redoc@2.5.4/bundles/redoc.standalone.js", ""),
    ],
)
def test_the_api_docs_let_their_scripts_talk_to_this_service_only(
    settings: Settings, path: str, script: str, root_path: str
) -> None:
    """Swagger UI and ReDoc come from cdn.jsdelivr.net without SRI and without a policy, on the origin of /ui/, whose
    reader's API key is in the sessionStorage: a compromised package could send it anywhere (audit 2026-09-29,
    S12). Scripts come from the one file and the page's own inline code, by its hash; requests go to the service."""
    client = TestClient(create_app(settings), root_path=root_path)
    page = client.get(path)

    assert page.status_code == 200 and f"https://cdn.jsdelivr.net/npm/{script}" in page.text
    policy = dict(part.strip().split(" ", 1) for part in page.headers["content-security-policy"].split(";"))
    assert (policy["default-src"], policy["connect-src"], policy["img-src"]) == ("'none'", "'self'", "'self' data:")
    assert policy["frame-ancestors"] == policy["base-uri"] == "'none'"
    scripts = policy["script-src"].split()
    inline = re.findall("<script>(.*?)</script>", page.text, flags=re.DOTALL)
    hashes = [f"'sha256-{base64.b64encode(hashlib.sha256(code.encode()).digest()).decode()}'" for code in inline]
    assert scripts == [f"https://cdn.jsdelivr.net/npm/{script}", *hashes]
    assert f"{root_path}/openapi.json" in page.text
    assert "fastapi.tiangolo.com" not in page.text and "fonts.googleapis.com" not in page.text  # no other hosts
    assert client.get("/openapi.json").status_code == 200


# A file of the CDN with its SHA-384, as a browser checks it: 48 bytes are 64 signs of base64
CHECKED = re.compile(
    r'(?:src|href)="(https://cdn\.jsdelivr\.net/npm/[^"]+)" integrity="sha384-[A-Za-z0-9+/]{64}" '
    r'crossorigin="anonymous"'
)


@pytest.mark.parametrize(("path", "files"), [("/docs", 2), ("/redoc", 1)])
def test_the_api_docs_load_their_files_by_version_and_checksum(settings: Settings, path: str, files: int) -> None:
    """The policy limits where a script may send, not what jsDelivr or npm serves: a changed file could still send the
    page elsewhere with a key in its address. With a fixed version and its SHA-384 the browser runs no other content
    (audit 2026-09-29, S12); a floating version such as @5 would change under its checksum."""
    page = TestClient(create_app(settings)).get(path)

    checked = CHECKED.findall(page.text)

    assert len(checked) == files and page.text.count("cdn.jsdelivr.net") == files
    assert all(re.search(r"@\d+\.\d+\.\d+/", url) for url in checked), checked


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


def test_shutdown_closes_the_local_indexes(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """The Wikidata and the GND index hold a connection each for the life of a worker; the lifespan closed only the
    HTTP clients, and the suite counted unclosed databases by the dozen (audit 2026-09-29, S1)."""
    state = tmp_path / "state"
    build_index(*write_dumps(tmp_path / "wikidata"), state / "wikidata.db")
    build_gnd_index(write_gnd_dumps(tmp_path / "gnd"), state / "gnd.db")
    app = create_app(make_settings(sample_zims.values(), state))
    assert app.state.wikidata.available and app.state.gnd.available

    with TestClient(app):
        pass

    assert not app.state.wikidata.available and not app.state.gnd.available


def test_settings_that_no_longer_exist_are_named_at_start(
    sample_zims: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # pydantic ignores unknown names, so a service configured with LLM_MODE_DEFAULT would silently run rule-based
    monkeypatch.setenv("LLM_MODE_DEFAULT", "hybrid-quality")
    monkeypatch.setenv("LLM_ROUTER_ENABLED", "true")
    monkeypatch.setenv("MATCHER_DEFAULT", "bm25")  # D53: the profile decides
    settings = make_settings(sample_zims.values(), tmp_path / "state")
    with caplog.at_level(logging.WARNING):
        create_app(settings)
    assert "LLM_MODE_DEFAULT" in caplog.text and "LLM_ROUTER_ENABLED" in caplog.text
    assert "MATCHER_DEFAULT" in caplog.text and "PRESET_DEFAULT" in caplog.text


def test_zim_paths_warns_that_it_bypasses_the_archive_management(
    sample_zims: dict[str, Path], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """docs/umbau.md U6: ZIM_PATHS is meant for development but also runs in production - silently, until now."""
    with caplog.at_level(logging.WARNING):
        create_app(make_settings(sample_zims.values(), tmp_path / "state"))
    assert "ZIM_PATHS" in caplog.text
    assert "active.json" in caplog.text, "the warning has to name what is bypassed"


def test_without_zim_paths_there_is_no_such_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    settings = make_settings([], tmp_path / "state", zim_dir=tmp_path / "zim")
    with caplog.at_level(logging.WARNING):
        create_app(settings)
    assert "ZIM_PATHS umgeht" not in caplog.text


def test_the_markdown_can_start_at_the_content(client: TestClient) -> None:
    """A caller who renders the document elsewhere does not want a YAML block in front of it.

    The frontmatter carries the AI Act disclosure, the review status and the snapshot of the archives,
    so it stays in by default and it stays in the answer either way - only the markdown drops it.
    """
    body = client.post(
        "/api/v2/compendium",
        json={"topic": "Optik", "parts": ["world"], "frontmatter_in_markdown": False},
    ).json()
    markdown = body["markdown"]
    assert markdown.startswith("# Kompendium: Optik"), markdown[:80]
    assert "kompendium_version" not in markdown, "the YAML block is what was asked to go"
    assert body["frontmatter"]["ai_disclosure"], "the disclosure is not lost, it moves to the field"


def test_the_markdown_carries_its_frontmatter_by_default(client: TestClient) -> None:
    """Nothing changes for a caller who does not ask: the document stays self-contained."""
    body = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"]}).json()
    assert body["markdown"].startswith("---\n"), body["markdown"][:60]
    assert "ai_disclosure" in body["markdown"]
