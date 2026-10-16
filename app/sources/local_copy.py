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
# A part this old belongs to a copy that died with its worker or container; a running copy writes on and stays younger
STALE_PART_S = 600.0
_CHUNK = 1 << 20

Version = tuple[int, int, int]


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
        self._failed: Version | None = None  # the version whose copy failed: read in place until the next one
        self._checked_at: float | None = None

    def path(self) -> Path:
        if self.directory is None:
            return self.source
        current, checked = self._current, self._checked_at
        recent = checked is not None and self._clock() - checked < self._recheck_s
        usable = current is not None and current.exists()
        if recent and (current is None or usable):
            return current or self.source
        # Another thread copying the next version takes seconds over the network: a whole previous copy serves
        # meanwhile, and only a reader without one waits (review of D113)
        if not self._lock.acquire(blocking=not usable):
            return current or self.source
        try:
            self._checked_at = self._clock()
            self._current = self._refresh(self.directory)
        finally:
            self._lock.release()
        return self._current or self.source

    def _refresh(self, directory: Path) -> Path | None:
        """The copy of the version on the volume now, made when there is none; ``None`` reads the file in place."""
        try:
            handle = self.source.open("rb")
        except FileNotFoundError:  # missing: its reader says so, as without a copy
            return None
        except OSError as exc:  # a stale handle or a timeout of the network file system passes: keep the copy
            log.debug("cannot look at %s (%s); keeping %s", self.source, exc, self._current)
            return self._current
        with handle:
            stat = os.fstat(handle.fileno())  # the version this handle reads, also when a swap comes meanwhile
            version = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
            target = directory / f"{self.source.stem}-{'-'.join(map(str, version))}{self.source.suffix}"
            with contextlib.suppress(OSError):  # another worker may remove an older copy meanwhile
                if target.stat().st_size == stat.st_size:
                    return target
            if version == self._failed:
                return None
            part = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.part")
            try:
                directory.mkdir(parents=True, exist_ok=True)
                with part.open("wb") as out:
                    shutil.copyfileobj(handle, out, _CHUNK)
                os.replace(part, target)
            except OSError as exc:
                # once per version: a full or read-only directory warned at every look, each a full read (review)
                log.warning("cannot copy %s to %s (%s); reading it in place", self.source.name, directory, exc)
                self._failed = version
                with contextlib.suppress(OSError):  # a leftover part; the directory may not even exist
                    part.unlink(missing_ok=True)
                return None
        log.info("copied %s (%d bytes) to %s", self.source.name, stat.st_size, target)
        self._prune(directory, target)
        return target

    def _prune(self, directory: Path, keep: Path) -> None:
        """Older copies but the newest of them, and parts a killed copy left behind. The previous copy stays until the
        next version: another worker may be about to open it, or may just have copied a version older than this one."""
        copies = []
        for path in directory.glob(f"{self.source.stem}-*{self.source.suffix}"):
            with contextlib.suppress(OSError):
                if path != keep:
                    copies.append((path.stat().st_mtime_ns, path))
        stale = [path for _, path in sorted(copies, reverse=True)[1:]]
        now = time.time()
        for part in directory.glob(f".{self.source.stem}-*{self.source.suffix}.*.part"):
            with contextlib.suppress(OSError):
                if now - part.stat().st_mtime > STALE_PART_S:
                    stale.append(part)
        for path in stale:
            try:
                path.unlink()
            except OSError as exc:  # Windows refuses while a connection holds it; the next version tries again
                log.debug("cannot remove %s: %s", path, exc)
