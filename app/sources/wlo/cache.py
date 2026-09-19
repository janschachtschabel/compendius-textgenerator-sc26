"""Small TTL cache for repository answers (PLAN.md 6.1: collections 1 h, material texts 7 days).

One SQLite file in STATE_DIR, shared by all API workers; values are JSON. Expiry is checked on read
against an injectable clock so tests never wait. Every write also sweeps expired entries, otherwise
texts of collections nobody asks for again would stay forever. The cache only saves time: when the
file cannot be used, reads are misses and writes are skipped, both logged.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA = "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)"
# Every write sweeps expired entries; without the index each write would scan the whole table
_INDEX = "CREATE INDEX IF NOT EXISTS cache_expires ON cache(expires_at)"


class TtlCache:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(path)
        self._clock = clock
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(_SCHEMA)
            connection.execute(_INDEX)
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5.0)

    def get(self, key: str) -> Any | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error as exc:
            log.warning("repository cache %s not readable, reading from the repository: %s", self._path, exc)
            return None
        if row is None or row[1] <= self._clock():
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any, *, ttl_s: float) -> None:
        now = self._clock()
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                    (key, json.dumps(value, ensure_ascii=False), now + ttl_s),
                )
                connection.execute("DELETE FROM cache WHERE expires_at <= ?", (now,))
                connection.commit()
        except sqlite3.Error as exc:
            log.warning("repository cache %s not writable, answer not cached: %s", self._path, exc)
