"""Collection endpoints and collection input for the compendium: overview, validation, repository failures."""

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.conftest import make_settings
from tests.test_wlo_client import BASE, OPTIK, UNKNOWN, FakeRepository


def _client(sample_zims: dict[str, Path], tmp_path: Path, repo: FakeRepository) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path / "state")
    app = create_app(settings)
    builder = CollectionBuilder(
        client=EduSharingClient(BASE, transport=httpx.MockTransport(repo), page_size=10),
        cache=TtlCache(tmp_path / "state" / "wlo_cache.db"),
    )
    app.state.collections = builder
    app.state.service.collections = builder
    return TestClient(app)


def test_overview_endpoint_returns_part_three(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _client(sample_zims, tmp_path, FakeRepository()) as client:
        body = client.get(f"/api/v2/collections/{OPTIK}/overview").json()
        assert body["available"] and body["title"] == "Optik"
        assert body["markdown"].startswith("## Teil 3 · Die Sammlung im Überblick")
        assert body["summary"]["materials"] == 16 and body["summary"]["subcollections"] == 4


def test_invalid_and_unknown_collection_ids(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _client(sample_zims, tmp_path, FakeRepository()) as client:
        assert client.get("/api/v2/collections/not-a-uuid/overview").status_code == 422
        assert client.get(f"/api/v2/collections/{UNKNOWN}/overview").status_code == 404
        assert client.post("/api/v2/compendium", json={"collection_id": UNKNOWN}).status_code == 404


def test_compendium_from_a_collection_and_repository_failure(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _client(sample_zims, tmp_path, FakeRepository()) as client:
        payload = {"collection_id": OPTIK, "parts": ["world", "collection"]}
        response = client.post("/api/v2/compendium", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["topic"] == "Optik" and body["collection"]["available"]
        assert body["frontmatter"]["parts"] == ["world", "collection"]
    with _client(sample_zims, tmp_path / "b", FakeRepository(fail=True)) as client:
        assert client.get(f"/api/v2/collections/{OPTIK}/overview").status_code == 502
        assert client.post("/api/v2/compendium", json={"collection_id": OPTIK}).status_code == 502


def test_repository_errors_say_what_failed_once(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _client(sample_zims, tmp_path / "a", FakeRepository()) as client:
        missing = client.post("/api/v2/compendium", json={"collection_id": UNKNOWN}).json()["detail"]
    assert missing == f"Sammlung {UNKNOWN} nicht gefunden"  # "Sammlung nicht gefunden: Sammlung … nicht gefunden"
    with _client(sample_zims, tmp_path / "b", FakeRepository(fail=True)) as client:
        overview = client.get(f"/api/v2/collections/{OPTIK}/overview").json()["detail"]
        compendium = client.post("/api/v2/compendium", json={"collection_id": OPTIK}).json()["detail"]
    for detail in (overview, compendium):
        assert detail.count("nicht erreichbar") == 1 and detail.count("edu-sharing") == 1, detail
