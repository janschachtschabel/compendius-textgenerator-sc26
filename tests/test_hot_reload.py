"""Archives follow active.json without a restart (PLAN.md 4.1, step 5)."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.sources.zim.active import ACTIVE_FILE, ActiveArchive, ActiveState, write_active
from app.sources.zim.refresh import RegistryRefresher
from app.sources.zim.registry import ZimRegistry
from tests.conftest import make_settings


def _entry(path: Path, archive_id: str, project: str) -> ActiveArchive:
    return ActiveArchive(id=archive_id, file=path.name, project=project)


def _copy_samples(sample_zims: dict[str, Path], target: Path) -> dict[str, Path]:
    return {project: Path(shutil.copy(path, target / path.name)) for project, path in sample_zims.items()}


def _state(local: dict[str, Path], *projects: str, profile: str = "") -> ActiveState:
    ids = {"wikipedia": "wikipedia_de_sample", "klexikon": "klexikon_de_sample"}
    return ActiveState(profile=profile, archives={ids[p]: _entry(local[p], ids[p], p) for p in projects})


def test_registry_reload_swaps_archives(sample_zims: dict[str, Path]) -> None:
    registry = ZimRegistry([sample_zims["wikipedia"]])
    assert [a.project for a in registry.archives] == ["wikipedia"]
    registry.reload([sample_zims["wikipedia"], sample_zims["klexikon"]])
    assert [a.project for a in registry.archives] == ["wikipedia", "klexikon"]
    registry.reload([])
    assert not registry.ready


def test_from_active_prefers_active_json_over_discovery(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    local = _copy_samples(sample_zims, tmp_path)
    assert [a.project for a in ZimRegistry.from_active(tmp_path).archives] == ["wikipedia", "klexikon"]
    write_active(tmp_path, _state(local, "klexikon"))
    assert [a.project for a in ZimRegistry.from_active(tmp_path).archives] == ["klexikon"]


def test_discovery_opens_only_the_newest_dump_of_an_archive(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """Without active.json both generations of an archive opened, and the older one led, as it sorts first (audit
    2026-09-29, Q2)."""
    for name in ("wikipedia_de_sample_2026-08.zim", "wikipedia_de_sample_2026-09.zim"):
        shutil.copy(sample_zims["wikipedia"], tmp_path / name)
    shutil.copy(sample_zims["klexikon"], tmp_path / sample_zims["klexikon"].name)

    registry = ZimRegistry.from_active(tmp_path)

    assert [a.file_name for a in registry.archives] == [
        "wikipedia_de_sample_2026-09.zim",
        "klexikon_de_sample_2026-08.zim",
    ]


def test_refresher_reopens_archives_on_change(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    registry = ZimRegistry.from_active(tmp_path)
    refresher = RegistryRefresher(registry, tmp_path)
    assert not registry.ready
    assert refresher.refresh() is False

    local = _copy_samples(sample_zims, tmp_path)
    write_active(tmp_path, _state(local, "klexikon"))
    assert refresher.refresh() is True
    assert [a.project for a in registry.archives] == ["klexikon"]
    assert refresher.refresh() is False

    state = _state(local, "wikipedia", "klexikon")
    state.archives["missing_de_sample"] = ActiveArchive(id="missing_de_sample", file="missing_de_sample_2026-01.zim")
    write_active(tmp_path, state)
    assert refresher.refresh() is True
    assert [a.project for a in registry.archives] == ["wikipedia", "klexikon"]  # the missing file is skipped


def test_refresher_keeps_registry_when_state_is_corrupt(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    local = _copy_samples(sample_zims, tmp_path)
    write_active(tmp_path, _state(local, "klexikon"))
    registry = ZimRegistry.from_active(tmp_path)
    refresher = RegistryRefresher(registry, tmp_path)
    (tmp_path / ACTIVE_FILE).write_text("{broken", encoding="utf-8")
    assert refresher.refresh() is False
    assert [a.project for a in registry.archives] == ["klexikon"]


def test_ready_flips_without_restart(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    settings = make_settings([], tmp_path / "state", zim_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/ready").status_code == 503
        local = _copy_samples(sample_zims, tmp_path)
        write_active(tmp_path, _state(local, "wikipedia", "klexikon", profile="compact"))
        assert client.get("/ready").status_code == 200
        status = client.get("/api/v2/zim/status").json()
        assert status["missing_required"] == []
        assert status["active"]["profile"] == "compact"
        assert {a["id"] for a in status["archives"]} == {"wikipedia_de_sample", "klexikon_de_sample"}
        assert client.post("/api/v2/compendium", json={"topic": "Optik"}).status_code == 200


def test_a_corrupt_state_file_leaves_the_registry_empty_instead_of_crashing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """TE-07: /ready then shows the problem, where a crash would loop until the sync rewrites the file."""
    (tmp_path / ACTIVE_FILE).write_text("{broken", encoding="utf-8")
    with caplog.at_level("ERROR"):
        registry = ZimRegistry.from_active(tmp_path)
    assert not registry.ready and registry.archives == []
    assert any(record.levelname == "ERROR" for record in caplog.records)
