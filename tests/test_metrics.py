"""Prometheus metrics: status gauges at scrape time, request and generation metrics, access and format."""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app import __version__
from app.api.body_limit import LARGE_BODY_BYTES
from app.jobs.runner import mark_alive
from app.jobs.zim_sync import ALIVE_FILE as ZIM_ALIVE_FILE
from app.llm.prompts import get_prompt
from app.main import create_app
from app.settings import Settings
from app.sources.gnd.index import build_gnd_index
from app.sources.gnd.sync import ALIVE_FILE as GND_ALIVE_FILE
from app.sources.lehrplan.harvest import ALIVE_FILE as LEHRPLAN_ALIVE_FILE
from app.sources.wikidata.index import build_index
from app.sources.wikidata.sync import ALIVE_FILE as WIKIDATA_ALIVE_FILE
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.conftest import ROOT, make_settings
from tests.test_gnd_index import write_dumps as write_gnd_dumps
from tests.test_lehrplan_api import write_cache
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_extraction import first_sentences
from tests.test_pipeline_llm import answer_from_evidence, make_gateway
from tests.test_pipeline_llm_matcher import leads_define_the_rest_is_content
from tests.test_wikidata_index import write_dumps
from tests.test_wlo_client import BASE, OPTIK, FakeRepository

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


def test_the_sync_and_harvest_loops_report_their_sign_of_life(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """BE-15 (audit 2026-09-28): the loops write the time into a file of their volume at least once an hour, and
    the API reports it; before the first one there is no series and no made-up zero."""
    client = _app(sample_zims, tmp_path)
    before = {name for name, _ in scrape(client)}
    (tmp_path / "zim").mkdir(parents=True, exist_ok=True)
    (tmp_path / "zim" / ZIM_ALIVE_FILE).write_text("2026-09-28T10:00:00+00:00", encoding="utf-8")
    (tmp_path / "state" / LEHRPLAN_ALIVE_FILE).write_text("2026-09-28T11:00:00+00:00", encoding="utf-8")

    samples = scrape(client)

    assert "kompendium_zim_sync_alive_timestamp_seconds" not in before
    assert "kompendium_lehrplan_harvest_alive_timestamp_seconds" not in before
    assert value(samples, "kompendium_zim_sync_alive_timestamp_seconds") == epoch("2026-09-28T10:00:00+00:00")
    assert value(samples, "kompendium_lehrplan_harvest_alive_timestamp_seconds") == epoch("2026-09-28T11:00:00+00:00")


def test_the_index_sync_loops_report_their_sign_of_life(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """The Wikidata and GND sidecars gave none: with an index built by hand and no sidecar ever started, no rule had a
    series to fire on (audit 2026-09-29, Q5)."""
    client = _app(sample_zims, tmp_path)
    before = {name for name, _ in scrape(client)}
    (tmp_path / "state" / WIKIDATA_ALIVE_FILE).write_text("2026-09-29T10:00:00+00:00", encoding="utf-8")
    (tmp_path / "state" / GND_ALIVE_FILE).write_text("2026-09-29T11:00:00+00:00", encoding="utf-8")

    samples = scrape(client)

    assert "kompendium_wikidata_sync_alive_timestamp_seconds" not in before
    assert "kompendium_gnd_sync_alive_timestamp_seconds" not in before
    assert value(samples, "kompendium_wikidata_sync_alive_timestamp_seconds") == epoch("2026-09-29T10:00:00+00:00")
    assert value(samples, "kompendium_gnd_sync_alive_timestamp_seconds") == epoch("2026-09-29T11:00:00+00:00")


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
    assert value(samples, "kompendium_build_info", revision="", version=__version__) == 1  # a local build
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


def test_a_running_sync_keeps_the_errors_and_end_of_the_last_finished_run(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    (tmp_path / "zim").mkdir()
    last = {"finished_at": "2026-09-18T01:00:00+00:00", "errors": ["wikipedia_de_sample: transfer failed"]}
    running = {"started_at": "2026-09-18T02:00:00+00:00", "finished_at": "", "errors": []}
    status = {"state": "running", "updated_at": "2026-09-18T02:05:00+00:00", "last_run": running, "last_finished": last}
    (tmp_path / "zim" / "sync_status.json").write_text(json.dumps(status), encoding="utf-8")
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    # Without them the error alert lost its series whenever a retry ran longer than a scrape interval
    assert value(samples, "kompendium_zim_sync_last_run_errors") == 1
    assert value(samples, "kompendium_zim_sync_last_run_timestamp_seconds") == epoch("2026-09-18T01:00:00+00:00")


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
    # Its alerts would stay silent: the failure itself is reported, per section
    assert value(samples, "kompendium_status_section_failed", section="curricula") == 1
    assert ("kompendium_status_section_failed", (("section", "archives"),)) in samples
    assert value(samples, "kompendium_status_section_failed", section="archives") == 0


def test_missing_status_files_leave_their_gauges_out(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    names = {name for name, _labels in samples}
    assert "kompendium_zim_sync_last_run_timestamp_seconds" not in names  # never synced: no fake zero timestamp
    assert "kompendium_lehrplan_cache_harvested_timestamp_seconds" not in names
    assert value(samples, "kompendium_lehrplan_cache_available") == 0


def test_the_wikidata_index_and_its_sync_are_gauges(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    build_index(*write_dumps(tmp_path / "dumps"), tmp_path / "state" / "wikidata.db")
    run = {"ok": False, "error": "SHA-1 mismatch", "finished_at": "2026-09-27T04:00:00+00:00"}
    (tmp_path / "state" / "wikidata_status.json").write_text(
        json.dumps({"state": "idle", "last_run": run}), encoding="utf-8"
    )
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    assert value(samples, "kompendium_wikidata_index_available") == 1
    assert value(samples, "kompendium_wikidata_index_dump_timestamp_seconds") == epoch("2026-09-07T00:00:00+00:00")
    assert value(samples, "kompendium_wikidata_sync_failed") == 1
    # Every daily check writes its end, one without a build too: a sidecar that stopped shows as an old time (BE-07)
    assert value(samples, "kompendium_wikidata_sync_last_run_timestamp_seconds") == epoch("2026-09-27T04:00:00+00:00")


def test_a_new_installation_without_the_index_reports_it_missing(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    names = {name for name, _labels in samples}
    assert samples[("kompendium_wikidata_index_available", ())] == 0  # present, so the alert can see it
    assert "kompendium_wikidata_index_dump_timestamp_seconds" not in names  # no index: no fake zero date
    assert "kompendium_wikidata_sync_failed" not in names  # the sidecar has not run yet
    assert "kompendium_wikidata_sync_last_run_timestamp_seconds" not in names  # no fake zero time either


def test_the_gnd_index_and_its_sync_are_gauges(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    build_gnd_index(write_gnd_dumps(tmp_path / "gnd"), tmp_path / "state" / "gnd.db")
    run = {"ok": False, "error": "SHA-256 mismatch", "finished_at": "2026-09-27T05:00:00+00:00"}
    (tmp_path / "state" / "gnd_status.json").write_text(
        json.dumps({"state": "idle", "last_run": run}), encoding="utf-8"
    )
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    assert value(samples, "kompendium_gnd_index_available") == 1
    assert value(samples, "kompendium_gnd_index_release_timestamp_seconds") == epoch("2026-02-17T00:00:00+00:00")
    assert value(samples, "kompendium_gnd_sync_failed") == 1
    assert value(samples, "kompendium_gnd_sync_last_run_timestamp_seconds") == epoch("2026-09-27T05:00:00+00:00")


def test_a_running_sync_reports_the_end_of_the_run_before(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """A build keeps the last run in its status while it runs: the time stays the last end, not a missing value."""
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "gnd_status.json").write_text(
        json.dumps(
            {
                "state": "running",
                "started_at": "2026-09-28T04:00:00+00:00",
                "last_run": {"ok": True, "finished_at": "2026-09-27T04:00:00+00:00"},
            }
        ),
        encoding="utf-8",
    )
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    assert value(samples, "kompendium_gnd_sync_last_run_timestamp_seconds") == epoch("2026-09-27T04:00:00+00:00")


def test_the_free_space_of_each_volume_is_a_gauge(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """A full volume stops the syncs and at last even their status files, and no gauge showed it (audit 2026-09-27,
    BE-07)."""
    (tmp_path / "zim").mkdir()
    (tmp_path / "state").mkdir()
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    free = shutil.disk_usage(tmp_path).free
    for volume in ("zim", "state"):
        key = ("kompendium_volume_free_bytes", (("volume", volume),))
        assert key in samples, volume
        assert abs(samples[key] - free) < 1 << 30  # other programs write to the same disk meanwhile


def test_a_volume_that_is_not_there_has_no_free_space_gauge(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """The development setup reads its archives from ZIM_PATHS and may have no ZIM_DIR: the free space of some parent
    directory would pass for the volume's."""
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    assert ("kompendium_volume_free_bytes", (("volume", "zim"),)) not in samples


def test_without_the_gnd_index_its_gauge_says_so(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _app(sample_zims, tmp_path) as client:
        samples = scrape(client)
    assert samples[("kompendium_gnd_index_available", ())] == 0
    assert "kompendium_gnd_sync_failed" not in {name for name, _labels in samples}


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


def test_a_body_refused_before_routing_is_counted_under_its_route(client: TestClient) -> None:
    """BodySizeLimit answers a declared length over the bound before the router runs, so the 413 had no route in its
    scope and counted as unmatched, beside the 404s (audit 2026-09-29, S8)."""
    small = client.app.state.settings.request_body_max_bytes + 10  # type: ignore[attr-defined]
    before = scrape(client)
    assert client.post("/api/v2/qa", content=b"x" * small).status_code == 413
    assert client.put("/api/v2/templates/eigen", content=b"x" * (LARGE_BODY_BYTES + 1)).status_code == 413
    after = scrape(client)

    def delta(route: str, method: str) -> float:
        labels = {"method": method, "route": route, "status": "413"}
        return value(after, "kompendium_http_requests_total", **labels) - value(
            before, "kompendium_http_requests_total", **labels
        )

    assert delta("/api/v2/qa", "POST") == 1
    assert delta("/api/v2/templates/{template_id}", "PUT") == 1
    assert delta("unmatched", "POST") == delta("unmatched", "PUT") == 0


def test_a_compendium_records_its_mode_phases_and_parts(client: TestClient) -> None:
    before = scrape(client)
    response = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world", "curricula"]})
    assert response.status_code == 200
    after = scrape(client)

    def delta(name: str, **labels: str) -> float:
        return value(after, name, **labels) - value(before, name, **labels)

    assert delta("kompendium_compendium_requests_total", llm_requested="false", llm_used="false") == 1
    for phase in ("resolve", "corpus", "match", "synthesize", "curricula"):
        assert delta("kompendium_compendium_phase_seconds_count", phase=phase) == 1
    available = "true" if response.json()["curricula"]["available"] else "false"
    assert delta("kompendium_parts_total", part="curricula", available=available) == 1


def test_llm_usage_of_a_compendium_is_counted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = make_gateway(FakeBApi(first_sentences, cached_tokens=10))
    monkeypatch.setattr(client.app.state.service, "llm", gateway)  # type: ignore[attr-defined]
    before = scrape(client)
    payload = {"topic": "Optik", "extraction": "llm", "generation": "llm-fast", "parts": ["world"]}
    response = client.post("/api/v2/compendium", json=payload)
    assert response.status_code == 200
    audit = response.json()["audit"]
    after = scrape(client)

    def delta(name: str, **labels: str) -> float:
        return value(after, name, **labels) - value(before, name, **labels)

    assert audit["llm_tokens"]["calls"] > 0
    route = "/api/v2/compendium"
    assert delta("kompendium_llm_tokens_total", endpoint=route, type="prompt") == audit["llm_tokens"]["prompt"]
    assert delta("kompendium_llm_tokens_total", endpoint=route, type="completion") == audit["llm_tokens"]["completion"]
    assert delta("kompendium_llm_calls_total", endpoint=route, outcome="answered") == audit["llm_tokens"]["calls"]
    # every answer of the fake read 10 prompt tokens from the cache
    assert audit["llm_tokens"]["cached"] == 10 * audit["llm_tokens"]["calls"]
    assert delta("kompendium_llm_tokens_total", endpoint=route, type="cached") == audit["llm_tokens"]["cached"]
    generation, extraction = audit["llm"]["generation"], audit["llm"]["extraction"]
    chosen = len(extraction["sections"]) - len(extraction["emptied"])
    assert chosen > 0 and delta("kompendium_llm_selections_total", outcome="chosen") == chosen
    assert delta("kompendium_llm_selections_total", outcome="fallback") == len(extraction["fallbacks"])
    assert delta("kompendium_llm_sections_total", outcome="written") == len(generation["sections"])
    assert delta("kompendium_llm_sentences_total", outcome="dropped") == generation["dropped_sentences"]
    assert delta("kompendium_compendium_requests_total", llm_requested="true", llm_used="true") == 1


def test_matcher_llm_counts_as_an_llm_request(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # A matcher=llm request that falls back to the rules has to reach the fallback alarm like the switches do
    payload = {"topic": "Optik", "matcher": "llm", "parts": ["world"]}
    service = client.app.state.service  # type: ignore[attr-defined]
    before = scrape(client)
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(leads_define_the_rest_is_content), per_request=1_000_000))
    available = service.llm_unavailable
    monkeypatch.setattr(
        service, "llm_unavailable", lambda: "LLM nicht verfügbar (b-api antwortet nicht); Regelmodus verwendet"
    )
    assert client.post("/api/v2/compendium", json=payload).status_code == 200  # the b-api is down: the rules
    monkeypatch.setattr(service, "llm_unavailable", available)
    assert client.post("/api/v2/compendium", json=payload).status_code == 200
    after = scrape(client)

    def delta(**labels: str) -> float:
        name = "kompendium_compendium_requests_total"
        return value(after, name, **labels) - value(before, name, **labels)

    assert delta(llm_requested="true", llm_used="false") == 1
    assert delta(llm_requested="true", llm_used="true") == 1


def naming_the_topic(body: dict[str, Any]) -> str:
    """N (D63) names the topic itself as its overview, and for "Programmiersprache" one more article of the sample
    archive as its part; every other question gets the first candidate."""
    if body["messages"][0]["content"] != get_prompt("topic_articles").system:
        return '{"wahl": 1}'
    topic = body["messages"][1]["content"].splitlines()[0].removeprefix("Thema: ")
    return json.dumps({"uebersicht": topic, "artikel": ["Sinfonie"] if topic == "Programmiersprache" else []})


def test_article_choice_llm_counts_as_an_llm_request_where_the_model_has_something_to_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Since D63 every topic asks the model for its overview and parts (N): "Programmiersprache" is such an article,
    # "Geometrische" is none, and then the model chooses among the rules' candidates. An answer that decides nothing
    # is a fallback the alarms (monitoring/alerts.yml) should see; llm-free asks nothing and counts as the rules.
    service = client.app.state.service  # type: ignore[attr-defined]
    before = scrape(client)
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(naming_the_topic), per_request=1_000_000))
    for topic in ("Geometrische", "Programmiersprache"):
        payload = {"topic": topic, "article_choice": "llm", "parts": ["world"]}
        assert client.post("/api/v2/compendium", json=payload).status_code == 200
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(lambda body: "weiß nicht"), per_request=1_000_000))
    payload = {"topic": "Geometrische", "article_choice": "llm", "parts": ["world"]}
    assert client.post("/api/v2/compendium", json=payload).status_code == 200  # unreadable: the rules' article
    payload = {"topic": "Programmiersprache", "preset": "llm-free", "parts": ["world"]}
    assert client.post("/api/v2/compendium", json=payload).status_code == 200
    after = scrape(client)

    def delta(**labels: str) -> float:
        name = "kompendium_compendium_requests_total"
        return value(after, name, **labels) - value(before, name, **labels)

    assert delta(llm_requested="true", llm_used="true") == 2
    assert delta(llm_requested="true", llm_used="false") == 1
    assert delta(llm_requested="false", llm_used="false") == 1


def test_metrics_can_require_a_token_or_be_switched_off(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    token = "geheim" * 6  # the service refuses a token under 16 characters (audit 2026-09-27, SE-08)
    with _app(sample_zims, tmp_path / "a", metrics_token=token) as client:
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer falsch"}).status_code == 401
        assert client.get("/metrics", headers={"Authorization": f"Bearer {token}"}).status_code == 200
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


def test_every_metric_the_alert_rules_use_is_exported(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    # promtool tests the rules against series named like the rules; only a real scrape catches a misspelt name
    rules = yaml.safe_load((ROOT / "monitoring" / "alerts.yml").read_text(encoding="utf-8"))
    used = {
        name
        for group in rules["groups"]
        for rule in group["rules"]
        for name in re.findall(r"\bkompendium_[a-z0-9_]+", rule["expr"])
    }
    write_cache(tmp_path / "state")
    finished = {"finished_at": "2026-09-18T03:00:00+00:00", "errors": []}
    (tmp_path / "state" / "lehrplan_status.json").write_text(
        json.dumps({"state": "idle", "last_run": finished}), encoding="utf-8"
    )
    (tmp_path / "state" / "wikidata_status.json").write_text(
        json.dumps({"state": "idle", "last_run": {**finished, "ok": True}}), encoding="utf-8"
    )
    (tmp_path / "state" / "gnd_status.json").write_text(
        json.dumps({"state": "idle", "last_run": {**finished, "ok": True}}), encoding="utf-8"
    )
    (tmp_path / "zim").mkdir()
    (tmp_path / "zim" / "sync_status.json").write_text(
        json.dumps({"state": "idle", "updated_at": "2026-09-18T03:00:00+00:00", "last_run": finished}), encoding="utf-8"
    )
    mark_alive(tmp_path / "zim" / ZIM_ALIVE_FILE)
    mark_alive(tmp_path / "state" / LEHRPLAN_ALIVE_FILE)
    mark_alive(tmp_path / "state" / WIKIDATA_ALIVE_FILE)
    mark_alive(tmp_path / "state" / GND_ALIVE_FILE)
    with _app(sample_zims, tmp_path) as client:
        gateway = make_gateway(FakeBApi(answer_from_evidence))
        gateway.check_model()
        client.app.state.llm = gateway  # type: ignore[attr-defined]
        assert client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"]}).status_code == 200
        exported = {name for name, _labels in scrape(client)}
    assert len(used) >= 10
    assert used <= exported, sorted(used - exported)


def test_part_three_and_the_knowledge_collection_are_counted(
    sample_zims: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _app(sample_zims, tmp_path) as client:
        repository = EduSharingClient(BASE, transport=httpx.MockTransport(FakeRepository()), page_size=10)
        builder = CollectionBuilder(client=repository, cache=TtlCache(tmp_path / "wlo_cache.db"))
        monkeypatch.setattr(client.app.state.service, "collections", builder)  # type: ignore[attr-defined]
        before = scrape(client)
        payload = {"topic": "Optik", "collection_id": OPTIK, "knowledge_collection_id": OPTIK}
        response = client.post("/api/v2/compendium", json={**payload, "parts": ["world", "collection"]})
        assert response.status_code == 200, response.text
        after = scrape(client)

    def delta(name: str, **labels: str) -> float:
        return value(after, name, **labels) - value(before, name, **labels)

    knowledge = response.json()["audit"]["knowledge"]
    assert delta("kompendium_parts_total", part="collection", available="true") == 1
    assert delta("kompendium_parts_total", part="knowledge", available="true") == 1
    assert knowledge["sources"] > 0
    assert delta("kompendium_knowledge_materials_total", outcome="used") == knowledge["sources"]
    assert delta("kompendium_knowledge_materials_total", outcome="skipped_license") == knowledge["skipped_license"]


def test_a_request_that_fails_inside_the_app_is_counted_as_500(
    sample_zims: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(make_settings(sample_zims.values(), tmp_path / "state", zim_dir=tmp_path / "zim"))

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(app.state.service, "generate", broken)
    with TestClient(app, raise_server_exceptions=False) as client:
        before = scrape(client)
        assert client.post("/api/v2/compendium", json={"topic": "Optik"}).status_code == 500
        after = scrape(client)
    labels = {"method": "POST", "route": "/api/v2/compendium", "status": "500"}
    assert (
        value(after, "kompendium_http_requests_total", **labels)
        - value(before, "kompendium_http_requests_total", **labels)
        == 1
    )


def test_the_sidecar_commands_start_with_the_api_metrics_variable_set(tmp_path: Path) -> None:
    # compose passes the same .env to every service; importing the API metrics there would open files in a
    # directory that only the API command creates, and the sync and harvest sidecars would crash at start
    environment = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(tmp_path / "gibt-es-nicht")}
    script = "import sys\nimport app.cli\nassert 'app.main' not in sys.modules\n"
    subprocess.run([sys.executable, "-c", script], env=environment, cwd=ROOT, check=True, timeout=120)  # noqa: S603


def test_every_endpoint_counts_its_llm_calls(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only POST /compendium counted LLM tokens and calls; /entities, /qa, /knowledge and the curriculum search
    called the LLM unseen (audit 2026-09-27, BE-04). budgeted_chat now counts every call by route and outcome."""
    from tests.test_entities_profiles import TEXT
    from tests.test_entities_profiles import model as naming_the_entities

    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(FakeBApi(naming_the_entities)))  # type: ignore[attr-defined]
    before = scrape(client)
    response = client.post("/api/v2/entities", json={"text": TEXT, "preset": "balanced"})
    assert response.status_code == 200, response.text
    failing = FakeBApi(statuses=[400])
    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(failing))  # type: ignore[attr-defined]
    assert client.post("/api/v2/entities", json={"text": TEXT, "preset": "balanced"}).status_code == 200
    after = scrape(client)

    def delta(name: str, **labels: str) -> float:
        return value(after, name, **labels) - value(before, name, **labels)

    route = "/api/v2/entities"
    assert delta("kompendium_llm_calls_total", endpoint=route, outcome="answered") == 1
    assert delta("kompendium_llm_calls_total", endpoint=route, outcome="failed") == 1
    assert delta("kompendium_llm_tokens_total", endpoint=route, type="prompt") > 0
    assert delta("kompendium_llm_tokens_total", endpoint=route, type="completion") > 0
