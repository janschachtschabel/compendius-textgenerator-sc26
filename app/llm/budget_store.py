"""Daily token counter shared by all API workers and kept across restarts: one SQLite file in ``STATE_DIR``.

The image runs several uvicorn workers; with a counter per process the daily cap would apply per worker. Only the
spent tokens are shared. Reservations of calls in flight stay in their process: they are short-lived and a crashed
worker must not leave them behind.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = "CREATE TABLE IF NOT EXISTS daily_tokens (day INTEGER PRIMARY KEY, used INTEGER NOT NULL)"
KEEP_DAYS = 30


class SqliteDailyStore:
    """Storage failures never stop the LLM layer: they are logged and the caller's own counter stays in charge."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(_SCHEMA)
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5.0)

    def used(self, day: int) -> int | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute("SELECT used FROM daily_tokens WHERE day = ?", (day,)).fetchone()
        except sqlite3.Error as exc:
            log.warning("LLM budget store not readable, counting in this process only: %s", exc)
            return None
        return int(row[0]) if row is not None else 0

    def add(self, day: int, tokens: int) -> bool:
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    "INSERT INTO daily_tokens (day, used) VALUES (?, ?) "
                    "ON CONFLICT(day) DO UPDATE SET used = used + excluded.used",
                    (day, tokens),
                )
                connection.execute("DELETE FROM daily_tokens WHERE day < ?", (day - KEEP_DAYS,))
                connection.commit()
        except sqlite3.Error as exc:
            log.warning("LLM budget store not writable, counting in this process only: %s", exc)
            return False
        return True
