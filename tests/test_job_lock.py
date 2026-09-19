"""Job lock: exclusive file with an identity, so a run never touches a lock another run has taken over."""

import os
import time
from pathlib import Path
from typing import Any

import pytest

from app.jobs.lock import LockHeldError, acquire_lock


def _acquire(path: Path, stale_s: float = 3600) -> Any:
    return acquire_lock(path, stale_s=stale_s, now=time.time, owner="pid 1\n")


def _take_over(path: Path) -> None:
    """What another run does after judging this lock stale: a new file at the same path."""
    path.unlink()
    path.write_text("pid 2\n", encoding="utf-8")


def test_a_run_does_not_release_a_lock_another_run_took_over(tmp_path: Path) -> None:
    lock = _acquire(tmp_path / "sync.lock")
    _take_over(lock.path)
    lock.release()  # the first run finishes late, after a pause longer than the staleness limit
    assert lock.path.read_text(encoding="utf-8") == "pid 2\n"  # the new holder keeps its lock


def test_a_run_does_not_refresh_a_lock_another_run_took_over(tmp_path: Path) -> None:
    lock = _acquire(tmp_path / "sync.lock")
    _take_over(lock.path)
    old = time.time() - 7200
    os.utime(lock.path, (old, old))
    lock.refresh()
    assert lock.path.stat().st_mtime == pytest.approx(old)  # its sign of life is not ours to give


def test_refresh_and_release_act_on_the_own_lock(tmp_path: Path) -> None:
    lock = _acquire(tmp_path / "sync.lock")
    old = time.time() - 7200
    os.utime(lock.path, (old, old))
    lock.refresh()
    assert time.time() - lock.path.stat().st_mtime < 60
    lock.release()
    assert not lock.path.exists()


def test_a_lock_released_between_the_attempt_and_the_look_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sync.lock"
    path.write_text("pid 2\n", encoding="utf-8")
    original = Path.stat
    calls: list[int] = []

    def released_meanwhile(self: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        if self == path and not calls:
            calls.append(1)
            self.unlink()  # the holder finished right after our exclusive create failed
            raise FileNotFoundError(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", released_meanwhile)
    lock = _acquire(path)  # a FileNotFoundError escaped before
    assert lock.path.read_text(encoding="utf-8") == "pid 1\n"


def test_a_fresh_lock_of_another_run_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "sync.lock"
    path.write_text("pid 2\n", encoding="utf-8")
    with pytest.raises(LockHeldError):
        _acquire(path)
