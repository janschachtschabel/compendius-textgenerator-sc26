"""Lock files for jobs that must never run twice at once on the same volume (curriculum harvest, ZIM sync).

The lock is a file created exclusively, so it also holds across processes and containers that share the
volume. A lock whose modification time is older than ``stale_s`` belongs to a crashed run and is taken over;
a foreign lock is never removed otherwise. A run remembers which file it created (device and inode), so a run
that paused past the limit neither refreshes nor removes the lock another run took over meanwhile.

simplify: the takeover of a stale lock checks the file again right before removing it, which leaves a window of
a few microseconds between two contenders; ``fcntl.flock`` would close it but does not exist on Windows.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class LockHeldError(RuntimeError):
    """Another run holds the lock; ``age_s`` is the time since its last sign of life (0 when unknown)."""

    def __init__(self, path: Path, age_s: float) -> None:
        super().__init__(f"{path} is held (age {age_s:.0f} s)")
        self.path = path
        self.age_s = age_s


def _identity(stat: os.stat_result) -> tuple[int, int]:
    return stat.st_dev, stat.st_ino


@dataclass(frozen=True)
class HeldLock:
    """The lock file this run created."""

    path: Path
    identity: tuple[int, int]

    def _ours(self) -> bool:
        try:
            return _identity(self.path.stat()) == self.identity
        except FileNotFoundError:
            return False

    def refresh(self) -> None:
        """Sign of life for the staleness rule; a lock another run took over is left alone."""
        if self._ours():
            os.utime(self.path)

    def release(self) -> None:
        if self._ours():
            self.path.unlink(missing_ok=True)


def acquire_lock(path: Path, *, stale_s: float, now: Callable[[], float], owner: str) -> HeldLock:
    """Create ``path`` exclusively and write ``owner`` into it; raise ``LockHeldError`` while another run holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(3):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stat = path.stat()
            except FileNotFoundError:  # released between the attempt and the look: try again
                continue
            age = now() - stat.st_mtime
            if age > stale_s:
                log.warning("removing stale lock %s (age %.0f s)", path, age)
                _remove_if_unchanged(path, stat)
                continue
            raise LockHeldError(path, max(age, 0)) from None
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(owner)
        return HeldLock(path, _identity(path.stat()))
    raise LockHeldError(path, 0)


def _remove_if_unchanged(path: Path, seen: os.stat_result) -> None:
    """Remove the stale lock only if it is still the file judged stale; another contender may have replaced it."""
    try:
        current = path.stat()
    except FileNotFoundError:
        return
    if _identity(current) == _identity(seen):
        path.unlink(missing_ok=True)
