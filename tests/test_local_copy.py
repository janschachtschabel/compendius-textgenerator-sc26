"""A file of the shared volume read from a copy on local disk (D113): pods on several nodes no longer read SQLite over
the network, and a sidecar's swap of the file is a local, atomic swap for each of them."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from app.sources.local_copy import LocalCopy


def write(path: Path, data: bytes) -> None:
    """As a sidecar does: a new file renamed into place."""
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "volume" / "lehrplan.db"
    path.parent.mkdir()
    write(path, b"first")
    return path


def test_without_a_directory_the_file_is_read_in_place(source: Path) -> None:
    assert LocalCopy(source, None).path() == source


def test_the_file_is_read_from_a_copy_on_local_disk(source: Path, tmp_path: Path) -> None:
    local = tmp_path / "local"

    path = LocalCopy(source, local).path()

    assert path.parent == local and path.read_bytes() == b"first"


def test_an_unchanged_file_is_copied_once(source: Path, tmp_path: Path) -> None:
    clock = Clock()
    copy = LocalCopy(source, tmp_path / "local", recheck_s=0, clock=clock)
    first = copy.path()
    stamp = first.stat().st_mtime_ns

    again = copy.path()

    assert again == first and again.stat().st_mtime_ns == stamp


def test_a_file_the_sidecar_replaced_is_copied_anew(source: Path, tmp_path: Path) -> None:
    clock = Clock()
    copy = LocalCopy(source, tmp_path / "local", recheck_s=60, clock=clock)
    old = copy.path()
    write(source, b"second version")

    assert copy.path() == old, "within the recheck time the copy stands"
    clock.now = 61
    new = copy.path()

    assert new != old and new.read_bytes() == b"second version"


def test_the_previous_copy_stays_until_a_third_version_comes(source: Path, tmp_path: Path) -> None:
    """Another worker may still be about to open the previous copy, or have just copied an older version than this
    one: deleting every other copy at once could pull a file from under a reader (review of D113)."""
    clock = Clock()
    copy = LocalCopy(source, tmp_path / "local", recheck_s=0, clock=clock)
    first = copy.path()
    write(source, b"second version")
    second = copy.path()
    write(source, b"third version, longer")
    third = copy.path()

    assert second.exists() and third.exists() and not first.exists()


def test_a_missing_file_is_named_as_it_is_so_its_reader_finds_it_missing(tmp_path: Path) -> None:
    missing = tmp_path / "volume" / "gnd.db"
    path = LocalCopy(missing, tmp_path / "local").path()
    assert path == missing and not path.exists()


def test_a_copy_that_fails_reads_the_file_in_place_and_says_so(
    source: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("a file where the directory should be", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app.sources.local_copy"):
        path = LocalCopy(source, blocked).path()

    assert path == source and "lehrplan.db" in caplog.text


def test_a_copy_someone_deleted_is_made_again(source: Path, tmp_path: Path) -> None:
    copy = LocalCopy(source, tmp_path / "local")
    first = copy.path()
    first.unlink()

    again = copy.path()

    assert again.read_bytes() == b"first"


def test_a_failed_copy_is_not_tried_again_until_a_new_version_comes(
    source: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A full or read-only directory made every look copy the whole file again over the network, with a warning each
    time - /health alone looks several times (review of D113)."""
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("a file where the directory should be", encoding="utf-8")
    copy = LocalCopy(source, blocked, recheck_s=0, clock=Clock())

    with caplog.at_level(logging.WARNING, logger="app.sources.local_copy"):
        paths = [copy.path() for _ in range(5)]
        write(source, b"second version")
        copy.path()

    assert paths == [source] * 5
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2, "once per version"


def test_a_part_a_killed_copy_left_behind_is_removed(source: Path, tmp_path: Path) -> None:
    """An emptyDir outlives a restarted container: parts of up to 277 MB filled it until the pod was evicted."""
    local = tmp_path / "local"
    local.mkdir()
    stale = local / ".lehrplan-1-2-3.db.99.1.part"
    stale.write_bytes(b"half")
    old = 1_000_000_000
    os.utime(stale, (old, old))
    fresh = local / ".lehrplan-4-5-6.db.98.1.part"
    fresh.write_bytes(b"still being written")

    LocalCopy(source, local).path()

    assert not stale.exists() and fresh.exists()


def test_a_passing_error_of_the_volume_keeps_the_copy(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale handle or a timeout of the network file system said "missing" and closed a working copy."""
    copy = LocalCopy(source, tmp_path / "local", recheck_s=0, clock=Clock())
    first = copy.path()
    real_open = Path.open

    def flaky(self: Path, *args: object, **kwargs: object) -> object:
        if self == source:
            raise OSError(116, "Stale file handle")
        return real_open(self, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Path, "open", flaky)

    assert copy.path() == first
