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


def test_a_file_the_sidecar_replaced_is_copied_anew_and_the_old_copy_goes(source: Path, tmp_path: Path) -> None:
    clock = Clock()
    copy = LocalCopy(source, tmp_path / "local", recheck_s=60, clock=clock)
    old = copy.path()
    write(source, b"second version")

    assert copy.path() == old, "within the recheck time the copy stands"
    clock.now = 61
    new = copy.path()

    assert new != old and new.read_bytes() == b"second version"
    assert not old.exists()


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
