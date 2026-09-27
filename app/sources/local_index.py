"""A local SQLite index that a sync writes while the service runs and the service only reads (D64, D65).

The Wikidata index and the GND index share this. A build writes the new file next to the old one (``.part``) and
swaps it in with one rename, so a reader never sees half a file. A reader opens the file read-only and checks its
schema; a missing or foreign file answers nothing instead of failing. It notices another file (inode, size or
modification time) at most ``recheck_s`` seconds later and opens that one, without a restart.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PART_SUFFIX = ".part"
RECHECK_S = 60.0  # how often a lookup looks whether the sync replaced the file; one stat a minute costs nothing


class IndexInUseError(OSError):
    """The new index is built, but the old one cannot be replaced - on Windows while a service holds it open."""


def write_atomically(target: Path, write: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    """Let ``write`` build the index in a file next to ``target``, then swap it in; the old index stays until then."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + PART_SUFFIX)
    partial.unlink(missing_ok=True)
    try:
        meta = write(partial)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    try:
        os.replace(partial, target)
    except PermissionError as exc:  # the finished build stays: it took minutes, the rename takes a moment
        raise IndexInUseError(
            f"{target} cannot be replaced - does a running service hold it open? The new index waits in {partial}; "
            f"stop the service and rename it to {target.name}"
        ) from exc
    return meta


class LocalIndex:
    """Read-only connection to an index file that a sync may replace while the service runs.

    A subclass names itself in the log (``label``), states the schema it reads (``schema``, the ``schema`` row of the
    ``meta`` table) and turns the ``meta`` rows into what ``meta()`` returns (``read_meta``); its lookups go through
    ``_first``.
    """

    label = "index"
    schema = ""

    def __init__(
        self, path: Path, *, recheck_s: float = RECHECK_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()  # one connection serves all request threads of a worker
        self._connection: sqlite3.Connection | None = None
        self._meta: dict[str, Any] = {}
        self._recheck_s, self._clock = recheck_s, clock
        self._checked_at = clock()
        self._identity: tuple[int, int, int] | None = None
        self._reopen(self._file_identity())

    def read_meta(self, rows: dict[str, str]) -> dict[str, Any]:
        return dict(rows)

    def _file_identity(self) -> tuple[int, int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return stat.st_ino, stat.st_size, stat.st_mtime_ns

    def _reopen(self, identity: tuple[int, int, int] | None) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection, self._meta, self._identity = None, {}, identity
        if identity is not None:
            self._open()

    def _recheck(self) -> None:
        now = self._clock()
        if now - self._checked_at < self._recheck_s:
            return
        self._checked_at = now
        identity = self._file_identity()
        if identity == self._identity:
            return
        with self._lock:
            if identity != self._identity:  # another request thread may have opened it meanwhile
                log.info("%s %s changed; opening it again", self.label, self.path)
                self._reopen(identity)

    def _open(self) -> None:
        # absolute(), not resolve(): on a mapped drive resolve() yields a UNC path, and SQLite refuses its URI
        uri = self.path.absolute().as_uri() + "?mode=ro"
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
            rows = dict(connection.execute("SELECT key, value FROM meta").fetchall())
            if rows.get("schema") != self.schema:
                raise sqlite3.DatabaseError(f"schema {rows.get('schema')!r}, expected {self.schema}")
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            log.error("%s %s is not usable: %s", self.label, self.path, exc)
            return
        self._connection, self._meta = connection, self.read_meta(rows)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def available(self) -> bool:
        self._recheck()
        return self._connection is not None

    def meta(self) -> dict[str, Any]:
        self._recheck()
        return dict(self._meta)

    def _first(self, sql: str, candidates: Sequence[tuple[Any, ...]]) -> tuple[Any, ...] | None:
        """The first row ``sql`` finds for one of the parameter tuples, in order; ``None`` without a usable file."""
        self._recheck()
        with self._lock:
            # Another request thread may have opened a new file since the look above, and a file that failed leaves none
            connection: sqlite3.Connection | None = self._connection
            if connection is None:
                return None
            for params in candidates:
                row = connection.execute(sql, params).fetchone()
                if row:
                    return tuple(row)
        return None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
