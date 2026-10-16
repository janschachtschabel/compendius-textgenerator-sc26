"""The write paths of the admin routes on a volume the service cannot write: mounted read-only (D113), full, or held by
another writer. Each answered 500 with no reason; a 503 says what is wrong and names no server path (audit
2026-10-16)."""

from __future__ import annotations

import errno
import io
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.locks import LockHeldError
from app.main import create_app
from app.sources.zim.active import ActiveArchive, ActiveState, write_active
from tests.conftest import make_settings

ADMIN_TOKEN = "s3cret" * 6
AUTH = {"X-Admin-Token": ADMIN_TOKEN}
TEMPLATE: dict[str, Any] = {
    "id": "mein",
    "name": "Mein Template",
    "slots": [{"id": "a", "slot": "praxis", "title": "Praxis"}],
}


def read_only(patch: pytest.MonkeyPatch) -> None:
    """Every write to the file system fails as on a read-only mount; reading goes on."""

    def refuse(*args: object, **kwargs: object) -> Any:
        raise OSError(errno.EROFS, "Read-only file system", str(args[0]) if args else None)

    real_open, real_os_open = io.open, os.open

    def open_reading(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in "wxa+"):
            refuse(file)
        return real_open(file, mode, *args, **kwargs)

    def os_open_reading(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            refuse(path)
        return real_os_open(path, flags, *args, **kwargs)

    for name in ("mkdir", "unlink", "replace", "rename", "remove"):
        patch.setattr(os, name, refuse)
    patch.setattr(io, "open", open_reading)
    patch.setattr(os, "open", os_open_reading)


@pytest.fixture
def client(sample_zims: dict[str, Path], tmp_path: Path) -> Iterator[TestClient]:
    zim_dir = tmp_path / "zim"
    zim_dir.mkdir()
    archives = {}
    for project, path in sample_zims.items():
        shutil.copy(path, zim_dir / path.name)
        archives[f"{project}_de_sample"] = ActiveArchive(id=f"{project}_de_sample", file=path.name, project=project)
    write_active(zim_dir, ActiveState(profile="compact", archives=archives))
    (zim_dir / "klexikon_de_sample_2025-01.zim").write_bytes(b"old")
    settings = make_settings([], tmp_path / "state", zim_dir=zim_dir, admin_token=ADMIN_TOKEN)
    with TestClient(create_app(settings)) as started:
        assert started.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH).status_code == 200
        yield started


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PUT", "/api/v2/templates/mein", TEMPLATE),
        ("DELETE", "/api/v2/templates/mein", None),
        ("POST", "/api/v2/zim/sync", None),
        ("DELETE", "/api/v2/zim/klexikon_de_sample_2025-01.zim", None),
        ("POST", "/api/v2/lehrplan/harvest", None),
    ],
)
def test_a_write_on_a_read_only_volume_is_a_503_that_says_why(
    client: TestClient, tmp_path: Path, method: str, path: str, body: dict[str, Any] | None
) -> None:
    with pytest.MonkeyPatch.context() as patch:
        read_only(patch)
        answer = client.request(method, path, json=body, headers=AUTH)

    assert answer.status_code == 503, answer.text
    detail = answer.json()["detail"]
    assert "nicht beschreibbar" in detail and str(tmp_path) not in detail


def test_a_template_write_meeting_a_held_lock_is_a_503_that_names_its_age(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def held(path: Path, **kwargs: object) -> None:
        raise LockHeldError(path, 42)

    monkeypatch.setattr("app.templates.manager.acquire_lock", held)
    monkeypatch.setattr("app.templates.manager.LOCK_WAIT_S", 0)

    answer = client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)

    assert answer.status_code == 503 and "42 s" in answer.json()["detail"]


def test_a_delete_during_a_sync_names_how_long_ago_the_sync_last_showed_life(
    client: TestClient, tmp_path: Path
) -> None:
    (tmp_path / "zim" / "sync.lock").write_text("pid 7", encoding="utf-8")

    refused = client.delete("/api/v2/zim/klexikon_de_sample_2025-01.zim", headers=AUTH)

    assert refused.status_code == 409 and " s" in refused.json()["detail"]
    assert "Lebenszeichen" in refused.json()["detail"]
