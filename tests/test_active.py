"""active.json: atomic state file for the archives in use, and the change watcher."""

from pathlib import Path

import pytest

from app.sources.zim.active import ACTIVE_FILE, ActiveArchive, ActiveState, ActiveWatcher, read_active, write_active


def _archive(file: str = "klexikon_de_all_maxi_2026-08.zim") -> ActiveArchive:
    return ActiveArchive(
        id="klexikon_de_all_maxi",
        file=file,
        uuid="0123",
        date="2026-08-07",
        project="klexikon",
        size=135008418,
        activated_at="2026-09-17T09:00:00Z",
    )


def test_roundtrip_is_atomic(tmp_path: Path) -> None:
    state = ActiveState(
        profile="compact", updated_at="2026-09-17T09:00:00Z", archives={"klexikon_de_all_maxi": _archive()}
    )
    path = write_active(tmp_path, state)
    assert path == tmp_path / ACTIVE_FILE
    assert [p.name for p in tmp_path.iterdir()] == [ACTIVE_FILE]  # no temp file left behind
    loaded = read_active(tmp_path)
    assert loaded == state
    assert loaded.paths(tmp_path) == [tmp_path / "klexikon_de_all_maxi_2026-08.zim"]


def test_missing_and_corrupt_files(tmp_path: Path) -> None:
    assert read_active(tmp_path) is None
    (tmp_path / ACTIVE_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        read_active(tmp_path)


def test_watcher_detects_changes(tmp_path: Path) -> None:
    watcher = ActiveWatcher(tmp_path)
    assert watcher.changed() is False
    write_active(tmp_path, ActiveState(profile="compact"))
    assert watcher.changed() is True
    assert watcher.changed() is False
    write_active(tmp_path, ActiveState(profile="compact", archives={"klexikon_de_all_maxi": _archive()}))
    assert watcher.changed() is True
    (tmp_path / ACTIVE_FILE).unlink()
    assert watcher.changed() is True
