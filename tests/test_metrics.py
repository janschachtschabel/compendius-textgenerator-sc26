"""Prometheus metrics: status gauges at scrape time, request and generation metrics, access and format."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app import __version__
from app.main import create_app
from app.settings import Settings
from tests.conftest import ROOT, make_settings
from tests.test_lehrplan_api import write_cache
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import answer_from_evidence, make_gateway

Samples = dict[tuple[str, tuple[tuple[str, str], ...]], float]


def scrape(client: TestClient) -> Samples:
    response = client.get("/metrics")
    assert response.status_code == 200, response.text
    return {
        (sample.name, tuple(sorted(sample.labels.items()))): sample.value
        for family in text_string_to_metric_families(response.text)
        for sample in family.samples
    }


def value(samples: Samples, name: str, **labels: str) -> float:
    return samples.get((name, tuple(sorted(labels.items()))), 0.0)


def epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def _app(sample_zims: dict[str, Path], tmp_path: Path, **overrides: Any) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path / "state", zim_dir=tmp_path / "zim", **overrides)
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_status_gauges_describe_archives_caches_and_sidecars(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    write_cache(tmp_path / "state")
    (tmp_path / "state" / "lehrplan_status.json").write_text(
        json.dumps({"state": "error", "last_run": {"finished_at": "2026-09-10T08:00:00+00:00"}}), encoding="utf-8"
    )
    (tmp_path / "zim").mkdir()
    (tmp_path / "zim" / "sync_status.json").write_text(
        json.dumps(
            {"state": "idle", "last_run": {"finished_at": "2026-09-01T03:00:00+00:00", "errors": ["x: HTTP 503"]}}
        ),
        encoding="utf-8",
    )
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    assert value(samples, "kompendium_build_info", version=__version__) == 1
    assert value(samples, "kompendium_zim_archives") == 2 and value(samples, "kompendium_zim_ready") == 1
    assert value(samples, "kompendium_zim_required_missing") == 0
    assert value(samples, "kompendium_zim_archive_articles", archive="wikipedia_de_sample") > 0
    assert value(samples, "kompendium_zim_sync_running") == 0
    assert value(samples, "kompendium_zim_sync_last_run_timestamp_seconds") == epoch("2026-09-01T03:00:00+00:00")
    assert value(samples, "kompendium_zim_sync_last_run_errors") == 1
    assert value(samples, "kompendium_lehrplan_cache_available") == 1
    harvested = epoch("2026-09-17T12:00:00+00:00")  # harvested_at of the cache written by write_cache
    assert value(samples, "kompendium_lehrplan_cache_harvested_timestamp_seconds") == harvested
    assert value(samples, "kompendium_lehrplan_harvest_failed") == 1
    assert value(samples, "kompendium_lehrplan_harvest_last_run_timestamp_seconds") == epoch(
        "2026-09-10T08:00:00+00:00"
    )
    assert value(samples, "kompendium_edu_sharing_enabled") == 1
    assert value(samples, "kompendium_llm_enabled") == 0 and value(samples, "kompendium_llm_available") == 0


def test_a_running_sync_reports_when_it_last_wrote_its_status(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    (tmp_path / "zim").mkdir()
    (tmp_path / "zim" / "sync_status.json").write_text(
        json.dumps(
            {
                "state": "running",
                "updated_at": "2026-09-18T01:00:00+00:00",
                "last_run": {"started_at": "2026-09-18T00:00:00+00:00", "finished_at": "", "errors": []},
            }
        ),
        encoding="utf-8",
    )
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    assert value(samples, "kompendium_zim_sync_running") == 1
    # A killed or stuck run stops writing: the alert compares this time with now
    assert value(samples, "kompendium_zim_sync_status_updated_timestamp_seconds") == epoch("2026-09-18T01:00:00+00:00")
    names = {name for name, _labels in samples}
    assert "kompendium_zim_sync_last_run_timestamp_seconds" not in names  # the running run has no end yet


def test_status_files_without_a_json_object_do_not_break_the_scrape(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "lehrplan_status.json").write_text("[]", encoding="utf-8")
    (tmp_path / "zim").mkdir()
    (tmp_path / "zim" / "sync_status.json").write_text("[1]", encoding="utf-8")
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)  # a 500 here would fire KompendiumDown although the API runs
    names = {name for name, _labels in samples}
    assert "kompendium_zim_sync_running" not in names and "kompendium_lehrplan_harvest_failed" not in names
    assert value(samples, "kompendium_zim_ready") == 1


def test_a_failing_status_section_leaves_the_others_in_the_scrape(
    sample_zims: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: object) -> None:
        raise RuntimeError("lehrplan.db locked")

    monkeypatch.setattr("app.observability.status.StatusCollector._curricula", broken)
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    assert value(samples, "kompendium_zim_ready") == 1 and value(samples, "kompendium_edu_sharing_enabled") == 1
    assert "kompendium_lehrplan_cache_available" not in {name for name, _labels in samples}


def test_missing_status_files_leave_their_gauges_out(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    names = {name for name, _labels in samples}
    assert "kompendium_zim_sync_last_run_timestamp_seconds" not in names  # never synced: no fake zero timestamp
    assert "kompendium_lehrplan_cache_harvested_timestamp_seconds" not in names
    assert value(samples, "kompendium_lehrplan_cache_available") == 0


def test_llm_gauges_show_availability_and_the_daily_budget(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _app(sample_zims, tmp_path) as client:
        gateway = make_gateway(FakeBApi(answer_from_evidence))
        gateway.check_model()  # as build_llm does at start; a scrape itself never calls the b-api
        client.app.state.llm = gateway  # type: ignore[attr-defined]
        samples = scrape(client)
    assert value(samples, "kompendium_llm_enabled") == 1 and value(samples, "kompendium_llm_available") == 1
    assert value(samples, "kompendium_llm_daily_budget_tokens") == 2_000_000
    assert value(samples, "kompendium_llm_tokens_used_today") == 0


def test_requests_are_counted_by_route_template(client: TestClient) -> None:
    before = scrape(client)
    assert client.get("/api/v2/templates/sc26").status_code == 200
    assert client.get("/gibt-es-nicht").status_code == 404
    after = scrape(client)

    def delta(name: str, **labels: str) -> float:
        return value(after, name, **labels) - value(before, name, **labels)

    template = "/api/v2/templates/{template_id}"
    assert delta("kompendium_http_requests_total", method="GET", route=template, status="200") == 1
    assert delta("kompendium_http_request_duration_seconds_count", method="GET", route=template) == 1
    assert delta("kompendium_http_requests_total", method="GET", route="unmatched", status="404") == 1
    routes = {dict(labels).get("route") for _name, labels in after}
    assert "/api/v2/templates/sc26" not in routes and "/gibt-es-nicht" not in routes  # no raw paths as labels
    assert "/metrics" not in routes  # scrapes are not requests of the service


def test_unusual_methods_share_one_label(client: TestClient) -> None:
    before = scrape(client)
    assert client.request("PROPFIND", "/health").status_code == 405
    assert client.request("X-SERIES-BOMB", "/health").status_code == 405
    after = scrape(client)
    counted = value(after, "kompendium_http_requests_total", method="other", route="/health", status="405")
    assert counted - value(before, "kompendium_http_requests_total", method="other", route="/health", status="405") == 2
    methods = {dict(labels).get("method") for _name, labels in after}
    assert "PROPFIND" not in methods and "X-SERIES-BOMB" not in methods  # clients cannot create new series


def test_the_api_docs_are_counted_under_their_own_path(client: TestClient) -> None:
    before = scrape(client)
    assert client.get("/openapi.json").status_code == 200
    after = scrape(client)

    def delta(name: str, **labels: str) -> float:
        return value(after, name, **labels) - value(before, name, **labels)

    assert delta("kompendium_http_requests_total", method="GET", route="/openapi.json", status="200") == 1
    assert delta("kompendium_http_requests_total", method="GET", route="unmatched", status="200") == 0


def test_a_compendium_records_its_mode_phases_and_parts(client: TestClient) -> None:
    before = scrape(client)
    response = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world", "curricula"]})
    assert response.status_code == 200
    after = scrape(client)

    def delta(name: str, **labels: str) -> float:
        return value(after, name, **labels) - value(before, name, **labels)

    modes = {"mode_requested": "rule-based", "mode_used": "rule-based"}
    assert delta("kompendium_compendium_requests_total", **modes) == 1
    for phase in ("resolve", "corpus", "match", "synthesize", "curricula"):
        assert delta("kompendium_compendium_phase_seconds_count", phase=phase) == 1
    available = "true" if response.json()["curricula"]["available"] else "false"
    assert delta("kompendium_parts_total", part="curricula", available=available) == 1


def test_llm_usage_of_a_hybrid_compendium_is_counted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = make_gateway(FakeBApi(answer_from_evidence))
    monkeypatch.setattr(client.app.state.service, "llm", gateway)  # type: ignore[attr-defined]
    before = scrape(client)
    response = client.post("/api/v2/compendium", json={"topic": "Optik", "mode": "hybrid-fast", "parts": ["world"]})
    assert response.status_code == 200
    audit = response.json()["audit"]
    after = scrape(client)

    def delta(name: str, **labels: str) -> float:
        return value(after, name, **labels) - value(before, name, **labels)

    assert audit["llm_tokens"]["calls"] > 0
    assert delta("kompendium_llm_tokens_total", type="prompt") == audit["llm_tokens"]["prompt"]
    assert delta("kompendium_llm_tokens_total", type="completion") == audit["llm_tokens"]["completion"]
    assert delta("kompendium_llm_calls_total") == audit["llm_tokens"]["calls"]
    assert delta("kompendium_llm_sections_total", outcome="written") == len(audit["llm"]["sections"])
    assert delta("kompendium_llm_sentences_total", outcome="dropped") == audit["llm"]["dropped_sentences"]
    assert delta("kompendium_compendium_requests_total", mode_requested="hybrid-fast", mode_used="hybrid-fast") == 1


def test_metrics_can_require_a_token_or_be_switched_off(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _app(sample_zims, tmp_path / "a", metrics_token="geheim") as client:
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer falsch"}).status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer geheim"}).status_code == 200
    with _app(sample_zims, tmp_path / "b", metrics_enabled=False) as client:
        assert client.get("/metrics").status_code == 404


def test_the_format_follows_the_accept_header(client: TestClient) -> None:
    classic = client.get("/metrics")
    assert classic.headers["content-type"].startswith("text/plain; version=0.0.4")
    openmetrics = client.get("/metrics", headers={"Accept": "application/openmetrics-text; version=1.0.0"})
    assert openmetrics.headers["content-type"].startswith("application/openmetrics-text")
    assert openmetrics.text.endswith("# EOF\n") and openmetrics.text.count("# EOF") == 1  # one registry, one end


def test_workers_are_summed_from_the_multiprocess_directory(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two processes record into the shared directory, as the uvicorn workers of the image do.
    script = "from app.observability.metrics import observe_request\nobserve_request('GET', '/worker', 200, 0.2)\n"
    environment = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}
    for _ in range(2):
        subprocess.run([sys.executable, "-c", script], env=environment, cwd=ROOT, check=True, timeout=120)  # noqa: S603
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    samples = scrape(client)
    assert value(samples, "kompendium_http_requests_total", method="GET", route="/worker", status="200") == 2
    assert value(samples, "kompendium_http_request_duration_seconds_count", method="GET", route="/worker") == 2
    assert value(samples, "kompendium_zim_ready") == 1  # the status is still read at scrape time
