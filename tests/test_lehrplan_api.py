"""Lehrplan endpoints: public status and search from the local cache, admin harvest request."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.sources.lehrplan.harvest import TRIGGER_FILE
from app.sources.lehrplan.store import SCHEMA_VERSION, LehrplanRecord, LehrplanWriter
from app.sources.lehrplan.tree import HarvestedNode
from tests.conftest import make_settings

AUTH = {"X-Admin-Token": "s3cret"}
PHYSIK = LehrplanRecord(
    iri="https://lp-sachsen.org/resource/522",
    label="Gymnasium Physik",
    bundesland_code="SN",
    bundesland="Sachsen",
    schularten=["Gymnasium"],
    schulfaecher=["Physik"],
    schulstufen=["Sekundarbereich I"],
)


def write_cache(state_dir: Path) -> None:
    writer = LehrplanWriter(state_dir / "lehrplan.db")
    writer.add_lehrplan(PHYSIK)
    node = HarvestedNode(
        iri="https://lp-sachsen.org/resource/7053",
        label="Lichtbrechung an Linsen",
        types=(),
        rollen=["kompetenz"],
        jahrgangsstufen=["Klassenstufe 7"],
        position=None,
    )
    node.parent_label = "Lernbereich 2: Optik"
    writer.add_nodes(PHYSIK.iri, [node])
    writer.set_meta(
        {"harvested_at": "2026-09-17T12:00:00+00:00", "counts": '{"SN": 1}', "endpoint": "https://sparql.test/"}
    )
    writer.commit()


def write_broken_cache(state_dir: Path) -> None:
    """A file that passes the schema check but lacks the node tables, as after an interrupted copy."""
    state_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(state_dir / "lehrplan.db")) as connection:
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        connection.commit()


def _client(sample_zims: dict[str, Path], tmp_path: Path, **overrides: Any) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path / "state", **overrides)
    return TestClient(create_app(settings))


def test_status_reports_a_missing_cache_and_then_its_meta(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _client(sample_zims, tmp_path) as client:
        body = client.get("/api/v2/lehrplan/status").json()
        assert body["available"] is False
        assert body["counts"] == {"lehrplaene": {}, "nodes": 0}
        write_cache(tmp_path / "state")
        body = client.get("/api/v2/lehrplan/status").json()
        assert body["available"] is True
        assert body["meta"]["harvested_at"].startswith("2026-09-17")
        assert body["counts"]["lehrplaene"] == {"SN": 1}
        assert body["coverage"]["states"] == ["Sachsen"]


def test_search_reads_the_cache_and_applies_the_subject(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        body = client.get("/api/v2/lehrplan/search", params={"q": "Optik"}).json()
        assert body["keywords"] == ["Optik"] and body["matches"][0]["label"] == "Lichtbrechung an Linsen"
        first = body["matches"][0]
        assert first["bundesland"] == "Sachsen" and first["schulstufe"] == "Sekundarstufe I"
        assert first["klassenstufe"] == "Klassenstufe 7" and first["lehrplan"] == "Gymnasium Physik"
        narrowed = client.get("/api/v2/lehrplan/search", params={"q": "Optik", "subject": "Chemie"}).json()
        assert narrowed["matches"] == [] and narrowed["subject_terms"] == [
            "chemie",
            "natur und technik",
            "naturwissenschaften",
        ]
        assert client.get("/api/v2/lehrplan/search", params={"q": "Op"}).status_code == 422


def test_harvest_request_is_admin_only_and_writes_the_trigger_file(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    with _client(sample_zims, tmp_path) as client:
        assert client.post("/api/v2/lehrplan/harvest").status_code == 404
    with _client(sample_zims, tmp_path, admin_token="s3cret") as client:
        assert client.post("/api/v2/lehrplan/harvest").status_code == 403
        assert client.post("/api/v2/lehrplan/harvest", headers=AUTH).status_code == 202
        assert (tmp_path / "state" / TRIGGER_FILE).exists()


def test_broken_cache_is_reported_as_unavailable_not_as_a_server_error(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    write_broken_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        search = client.get("/api/v2/lehrplan/search", params={"q": "Optik"})
        assert search.status_code == 200 and search.json()["available"] is False
        status = client.get("/api/v2/lehrplan/status")
        assert status.status_code == 200 and status.json()["counts"] == {"lehrplaene": {}, "nodes": 0}


def test_public_answers_do_not_reveal_server_paths(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _client(sample_zims, tmp_path) as client:
        status = client.get("/api/v2/lehrplan/status").json()
        compendium = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["curricula"]}).json()
    assert "db_path" not in status and str(tmp_path) not in str(status)
    assert compendium["curricula"]["summary"] == {"reason": "cache_missing"}
