"""Lock files for jobs that must never run twice at once on the same volume (curriculum harvest, ZIM sync).

The lock is a file created exclusively, so it also holds across processes and containers that share the
volume. A lock whose modification time is older than ``stale_s`` belongs to a crashed run and is taken over;
a foreign lock is never removed otherwise.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


class LockHeldError(RuntimeError):
    """Another run holds the lock; ``age_s`` is the time since its last sign of life (0 when unknown)."""

    def __init__(self, path: Path, age_s: float) -> None:
        super().__init__(f"{path} is held (age {age_s:.0f} s)")
        self.path = path
        self.age_s = age_s


def acquire_lock(path: Path, *, stale_s: float, now: Callable[[], float], owner: str) -> Path:
    """Create ``path`` exclusively and write ``owner`` into it; raise ``LockHeldError`` while another run holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = now() - path.stat().st_mtime
            if age > stale_s:
                log.warning("removing stale lock %s (age %.0f s)", path, age)
                path.unlink(missing_ok=True)
                continue
            raise LockHeldError(path, max(age, 0)) from None
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(owner)
        return path
    raise LockHeldError(path, 0)
