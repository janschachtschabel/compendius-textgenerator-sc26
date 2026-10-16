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
import re
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from pathlib import Path

log = logging.getLogger(__name__)

RECHECK_S = 60.0  # how often a look checks the volume for a new version; one stat a minute costs nothing
# A part this old belongs to a copy that died with its worker or container; a running copy writes on and stays younger
STALE_PART_S = 600.0
# A failed copy - a hiccup of the network, a full disk - is tried again after this; meanwhile the file is read in place
RETRY_FAILED_S = 900.0
_CHUNK = 1 << 20

Version = tuple[int, int, int]

# Off in the probes: /health and /ready have a few seconds, and a new version of lehrplan.db is 277 MB to copy over the
# network. They read the copy there is; the next request copies (audit 2026-10-16).
_copying: ContextVar[bool] = ContextVar("local_copy_copying", default=True)


@contextlib.contextmanager
def deferred_copies() -> Iterator[None]:
    """Within it no ``path()`` copies a new version: it names the copy there is, or the file on the volume."""
    token = _copying.set(False)
    try:
        yield
    finally:
        _copying.reset(token)


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
        self._failed: tuple[Version, float] | None = None  # a version whose copy failed, and when
        self._checked_at: float | None = None

    def path(self) -> Path:
        if self.directory is None:
            return self.source
        current, checked = self._current, self._checked_at
        recent = checked is not None and self._clock() - checked < self._recheck_s
        usable = current is not None and current.exists()
        if (recent and (current is None or usable)) or not _copying.get():
            return current if current is not None and usable else self.source
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
            if self._failed is not None and self._failed[0] == version:
                if self._clock() - self._failed[1] < RETRY_FAILED_S:
                    return None
            part = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.part")
            started = self._clock()
            try:
                directory.mkdir(parents=True, exist_ok=True)
                with part.open("wb") as out:
                    shutil.copyfileobj(handle, out, _CHUNK)
                os.replace(part, target)
            except OSError as exc:
                with contextlib.suppress(OSError):  # another worker renamed its copy of this version into place first
                    if target.stat().st_size == stat.st_size:
                        part.unlink(missing_ok=True)
                        return target
                # once per version: a full or read-only directory warned at every look, each a full read (review)
                log.warning("cannot copy %s to %s (%s); reading it in place", self.source.name, directory, exc)
                self._failed = (version, self._clock())
                with contextlib.suppress(OSError):  # a leftover part; the directory may not even exist
                    part.unlink(missing_ok=True)
                return None
        # the seconds tell on the cluster's storage whether RETRY_FAILED_S fits (audit 2026-10-16, C13)
        took = self._clock() - started
        log.info("copied %s (%d bytes) to %s in %.1f s", self.source.name, stat.st_size, target, took)
        self._prune(directory, target)
        return target

    def _prune(self, directory: Path, keep: Path) -> None:
        """Older copies but the newest of them, and parts a killed copy left behind. The previous copy stays until the
        next version: another worker may be about to open it, or may just have copied a version older than this one."""
        # exactly the names made here: the directory may hold other files, a lehrplan-backup.db say (audit 2026-10-16)
        stem, suffix = re.escape(self.source.stem), re.escape(self.source.suffix)
        own_copy = re.compile(rf"{stem}-\d+-\d+-\d+{suffix}")
        own_part = re.compile(rf"\.{stem}-\d+-\d+-\d+{suffix}\.\d+\.\d+\.part")
        copies, stale = [], []
        now = time.time()
        for path in directory.iterdir():
            with contextlib.suppress(OSError):
                if own_copy.fullmatch(path.name) and path != keep:
                    copies.append((path.stat().st_mtime_ns, path))
                elif own_part.fullmatch(path.name) and now - path.stat().st_mtime > STALE_PART_S:
                    stale.append(path)
        stale += [path for _, path in sorted(copies, reverse=True)[1:]]
        for path in stale:
            try:
                path.unlink()
            except OSError as exc:  # Windows refuses while a connection holds it; the next version tries again
                log.debug("cannot remove %s: %s", path, exc)
