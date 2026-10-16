"""A file of the shared volume, read from a copy on the pod's local disk (D113).

Pods on several nodes read the SQLite files of the sidecars (``lehrplan.db``, ``wikidata.db``, ``gnd.db``) over a
network file system, and a read that met a sidecar's swap there could fail. With ``INDEX_COPY_DIR`` each pod copies the
file once per version into that directory - an ``emptyDir`` on local disk - and reads the copy; the next version is a
new copy, swapped in locally and atomically. The copy is named by the identity of the file it came from (inode, size,
modification time), so the workers of a pod share it, and a file read at the moment of a swap still yields the
version it opened. Without the directory, or when a copy fails, the file is read in place as before.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

RECHECK_S = 60.0  # how often a look checks the volume for a new version; one stat a minute costs nothing
_CHUNK = 1 << 20


class LocalCopy:
    """``path()`` names the file to read: the local copy of the current version of ``source``, or ``source`` itself."""

    def __init__(
        self,
        source: Path,
        directory: Path | None,
        *,
        recheck_s: float = RECHECK_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = Path(source)
        self.directory = Path(directory) if directory is not None else None
        self._recheck_s, self._clock = recheck_s, clock
        self._lock = threading.Lock()
        self._current: Path | None = None
        self._checked_at = 0.0

    def path(self) -> Path:
        if self.directory is None:
            return self.source
        current = self._current
        if current is not None and self._clock() - self._checked_at < self._recheck_s and current.exists():
            return current
        with self._lock:
            self._checked_at = self._clock()
            self._current = self._refresh(self.directory)
        return self._current or self.source

    def _refresh(self, directory: Path) -> Path | None:
        """The copy of the version on the volume now, made when there is none; ``None`` reads the file in place."""
        try:
            handle = self.source.open("rb")
        except OSError:  # missing: its reader says so, as without a copy
            return None
        with handle:
            stat = os.fstat(handle.fileno())  # the version this handle reads, also when a swap comes meanwhile
            version = f"{stat.st_ino}-{stat.st_size}-{stat.st_mtime_ns}"
            target = directory / f"{self.source.stem}-{version}{self.source.suffix}"
            if target.is_file() and target.stat().st_size == stat.st_size:
                return target
            part = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.part")
            try:
                directory.mkdir(parents=True, exist_ok=True)
                with part.open("wb") as out:
                    shutil.copyfileobj(handle, out, _CHUNK)
                os.replace(part, target)
            except OSError as exc:
                log.warning("cannot copy %s to %s (%s); reading it in place", self.source.name, directory, exc)
                with contextlib.suppress(OSError):  # a leftover part; the directory may not even exist
                    part.unlink(missing_ok=True)
                return None
        log.info("copied %s (%d bytes) to %s", self.source.name, stat.st_size, target)
        self._remove_others(directory, target)
        return target

    def _remove_others(self, directory: Path, keep: Path) -> None:
        """Older copies of this file: a worker that still reads one keeps its open file on Linux."""
        for older in directory.glob(f"{self.source.stem}-*{self.source.suffix}"):
            if older != keep:
                try:
                    older.unlink()
                except OSError as exc:  # Windows refuses while a connection holds it; the next version tries again
                    log.debug("cannot remove %s: %s", older, exc)
