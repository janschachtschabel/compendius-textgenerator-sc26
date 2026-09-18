"""Small TTL cache for repository answers (PLAN.md 6.1: collections 1 h, material texts 7 days).

One SQLite file in STATE_DIR, shared by all API workers; values are JSON. Expiry is checked on read
against an injectable clock so tests never wait.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

_SCHEMA = "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)"


class TtlCache:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(path)
        self._clock = clock
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(_SCHEMA)
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5.0)

    def get(self, key: str) -> Any | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            if row[1] <= self._clock():
                connection.execute("DELETE FROM cache WHERE key = ?", (key,))
                connection.commit()
                return None
            return json.loads(row[0])

    def set(self, key: str, value: Any, *, ttl_s: float) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), self._clock() + ttl_s),
            )
            connection.commit()
