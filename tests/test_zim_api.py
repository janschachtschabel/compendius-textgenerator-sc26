"""ZIM endpoints: public status with sync info, admin protection, catalog, sync trigger, delete."""

import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.jobs.zim_sync import TRIGGER_FILE
from app.main import create_app
from app.sources.zim.active import ActiveArchive, ActiveState, write_active
from app.sources.zim.catalog import KiwixCatalog
from tests.conftest import make_settings, strings_in

OPDS = Path(__file__).parent / "fixtures" / "opds"
AUTH = {"X-Admin-Token": "s3cret"}


@pytest.fixture
def zim_dir(sample_zims: dict[str, Path], tmp_path: Path) -> Path:
    directory = tmp_path / "zim"
    directory.mkdir()
    archives = {}
    for project, path in sample_zims.items():
        shutil.copy(path, directory / path.name)
        archive_id = f"{project}_de_sample"
        archives[archive_id] = ActiveArchive(id=archive_id, file=path.name, project=project)
    write_active(directory, ActiveState(profile="compact", archives=archives))
    return directory


def _client(zim_dir: Path, tmp_path: Path, **overrides: Any) -> TestClient:
    settings = make_settings([], tmp_path / "state", zim_dir=zim_dir, **overrides)
    return TestClient(create_app(settings))


def test_status_includes_active_and_sync_state(zim_dir: Path, tmp_path: Path) -> None:
    with _client(zim_dir, tmp_path) as client:
        body = client.get("/api/v2/zim/status").json()
        assert body["active"]["profile"] == "compact"
        assert body["sync"] is None
        assert body["missing_required"] == []
        assert body["required"] == ["wikipedia_de_sample", "klexikon_de_sample"]


def test_admin_endpoints_are_hidden_without_token(zim_dir: Path, tmp_path: Path) -> None:
    with _client(zim_dir, tmp_path) as client:
        assert client.get("/api/v2/zim/catalog").status_code == 404
        assert client.post("/api/v2/zim/sync").status_code == 404
        assert client.get("/api/v2/zim/progress", headers=AUTH).status_code == 404


def test_admin_endpoints_require_the_token(zim_dir: Path, tmp_path: Path) -> None:
    with _client(zim_dir, tmp_path, admin_token="s3cret") as client:
        assert client.get("/api/v2/zim/progress").status_code == 403
        assert client.get("/api/v2/zim/progress", headers={"X-Admin-Token": "wrong"}).status_code == 403
        response = client.get("/api/v2/zim/progress", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["state"] == "unknown"


def test_catalog_marks_subscribed_and_installed(zim_dir: Path, tmp_path: Path) -> None:
    feed = (OPDS / "klexikon_de_all.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=feed)

    with _client(zim_dir, tmp_path, admin_token="s3cret") as client:
        client.app.state.catalog = KiwixCatalog(client=httpx.Client(transport=httpx.MockTransport(handler)))
        entries = client.get("/api/v2/zim/catalog", headers=AUTH).json()
        by_id = {e["archive_id"]: e for e in entries}
        assert by_id["klexikon_de_all_maxi"]["subscribed"] is True  # config/zim_subscriptions.yaml
        assert by_id["klexikon_de_all_nopic"]["subscribed"] is False
        assert by_id["klexikon_de_all_maxi"]["installed"] is False
        assert by_id["klexikon_de_all_maxi"]["download_url"].endswith("klexikon_de_all_maxi_2026-08.zim")


def test_catalog_failure_is_a_502(zim_dir: Path, tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with _client(zim_dir, tmp_path, admin_token="s3cret") as client:
        client.app.state.catalog = KiwixCatalog(client=httpx.Client(transport=httpx.MockTransport(handler)))
        assert client.get("/api/v2/zim/catalog", headers=AUTH).status_code == 502


def test_sync_trigger_writes_request_file(zim_dir: Path, tmp_path: Path) -> None:
    with _client(zim_dir, tmp_path, admin_token="s3cret") as client:
        response = client.post("/api/v2/zim/sync", headers=AUTH)
        assert response.status_code == 202
        assert response.json()["requested"] is True
        assert (zim_dir / TRIGGER_FILE).exists()


def test_delete_refuses_active_and_removes_stray_files(
    zim_dir: Path, tmp_path: Path, sample_zims: dict[str, Path]
) -> None:
    stray = zim_dir / "klexikon_de_sample_2025-01.zim"
    stray.write_bytes(b"old")
    part = zim_dir / "klexikon_de_sample_2025-01.zim.part"
    part.write_bytes(b"partial")
    with _client(zim_dir, tmp_path, admin_token="s3cret") as client:
        assert client.delete(f"/api/v2/zim/{sample_zims['klexikon'].name}", headers=AUTH).status_code == 409
        assert client.delete("/api/v2/zim/not-there.zim", headers=AUTH).status_code == 404
        assert client.delete("/api/v2/zim/notes.txt", headers=AUTH).status_code == 400
        response = client.delete("/api/v2/zim/klexikon_de_sample_2025-01.zim", headers=AUTH)
        assert response.status_code == 200
        assert sorted(response.json()["removed"]) == [stray.name, part.name]
        assert not stray.exists()
        assert not part.exists()


def test_the_public_status_leaves_the_error_texts_of_the_sync_to_the_admin(zim_dir: Path, tmp_path: Path) -> None:
    part = zim_dir / "wikipedia_de_sample_2026-09.zim.part"
    errors = [f"wikipedia_de_sample: [Errno 28] No space left on device: '{part}'"]
    last_run = {"profile": "compact", "started_at": "2026-09-18T03:00:00+00:00"}
    last_run |= {"finished_at": "2026-09-18T03:20:00+00:00", "downloaded": [], "errors": errors}
    status = {"state": "idle", "updated_at": "2026-09-18T03:20:00+00:00", "last_run": last_run, "download": None}
    (zim_dir / "sync_status.json").write_text(json.dumps(status), encoding="utf-8")
    with _client(zim_dir, tmp_path, admin_token="s3cret") as client:
        public = client.get("/api/v2/zim/status").json()["sync"]
        progress = client.get("/api/v2/zim/progress", headers=AUTH).json()
    assert public["state"] == "idle" and public["last_run"]["finished_at"] == "2026-09-18T03:20:00+00:00"
    assert public["last_run"]["error_count"] == 1
    assert not any(str(tmp_path) in text or "Errno" in text for text in strings_in(public))
    assert progress["last_run"]["errors"] == errors  # the admin endpoint keeps the detail
