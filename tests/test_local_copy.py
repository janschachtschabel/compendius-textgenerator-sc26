"""A file of the shared volume read from a copy on local disk (D113): pods on several nodes no longer read SQLite over
the network, and a sidecar's swap of the file is a local, atomic swap for each of them."""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path

import pytest

from app.sources.local_copy import RETRY_FAILED_S, LocalCopy, deferred_copies


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


def test_a_reader_meanwhile_gets_the_previous_copy_instead_of_waiting_for_a_running_copy(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copying a new lehrplan.db over the network takes seconds; the other threads of the worker waited for it, the
    probes too, although a whole previous copy lay ready (review of D113)."""
    copy = LocalCopy(source, tmp_path / "local", recheck_s=0, clock=Clock())
    first = copy.path()
    write(source, b"second version")
    started, release = threading.Event(), threading.Event()
    real_copy = shutil.copyfileobj

    def slow(*args: object, **kwargs: object) -> None:
        started.set()
        release.wait(5)
        real_copy(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.sources.local_copy.shutil.copyfileobj", slow)
    copier = threading.Thread(target=copy.path)
    copier.start()
    assert started.wait(5)
    seen: list[Path] = []
    reader = threading.Thread(target=lambda: seen.append(copy.path()))
    reader.start()
    reader.join(2)
    waited = reader.is_alive()
    release.set()
    copier.join(5)
    reader.join(5)

    assert not waited and seen == [first]
    assert copy.path().read_bytes() == b"second version"


def test_one_worker_s_new_copy_leaves_the_copy_another_worker_reads(source: Path, tmp_path: Path) -> None:
    """The workers of a pod share the directory: a worker that copies the next version must not remove the version
    another worker still reads."""
    local = tmp_path / "local"
    a = LocalCopy(source, local, recheck_s=0, clock=Clock())
    b = LocalCopy(source, local, recheck_s=60, clock=Clock())
    a.path()
    read_by_b = b.path()
    write(source, b"second version")

    a.path()

    assert read_by_b.exists() and b.path() == read_by_b


def test_a_copy_another_worker_renamed_into_place_first_is_used(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Two workers copy the same version at the start; on Windows the slower one's rename fails while the other's copy
    is open, and the version counted as failed for good (audit 2026-10-16)."""
    real_replace = os.replace

    def lost(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        real_replace(src, dst)  # the other worker's copy is in place now
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr("app.sources.local_copy.os.replace", lost)
    with caplog.at_level(logging.WARNING, logger="app.sources.local_copy"):
        path = LocalCopy(source, tmp_path / "local").path()

    assert path.parent == tmp_path / "local" and path.read_bytes() == b"first"
    assert "cannot copy" not in caplog.text


def test_a_failed_copy_is_tried_again_after_a_while(source: Path, tmp_path: Path) -> None:
    """A network hiccup or a full disk read the volume until the next version, days later (audit 2026-10-16)."""
    local = tmp_path / "local"
    local.write_text("in the way", encoding="utf-8")
    clock = Clock()
    copy = LocalCopy(source, local, recheck_s=0, clock=clock)
    assert copy.path() == source
    local.unlink()

    clock.now = RETRY_FAILED_S - 1
    assert copy.path() == source, "not yet"
    clock.now = RETRY_FAILED_S + 1
    assert copy.path().parent == local


def test_tidying_up_leaves_files_the_service_did_not_make(source: Path, tmp_path: Path) -> None:
    """INDEX_COPY_DIR on a directory shared with other files: lehrplan-backup.db matched the pattern of the copies."""
    local = tmp_path / "local"
    local.mkdir()
    foreign = local / "lehrplan-backup.db"
    foreign.write_bytes(b"someone's backup")
    copy = LocalCopy(source, local, recheck_s=0, clock=Clock())
    for version in (b"one", b"two, longer", b"three, longer still"):
        write(source, version)
        copy.path()

    assert foreign.exists()


def test_a_probe_reads_the_present_copy_and_leaves_a_new_version_to_a_request(source: Path, tmp_path: Path) -> None:
    """/health and /ready have five seconds; the probe that met a new version first copied 277 MB over the network
    (audit 2026-10-16)."""
    local = tmp_path / "local"
    copy = LocalCopy(source, local, recheck_s=0, clock=Clock())
    first = copy.path()
    write(source, b"second version")

    with deferred_copies():
        assert copy.path() == first
    assert len(list(local.glob("lehrplan-*.db"))) == 1, "the probe made no copy"
    assert copy.path().read_bytes() == b"second version"
