"""Daily token counter shared by all API workers and kept across restarts: one SQLite file in ``STATE_DIR``.

The image runs several uvicorn workers; with a counter per process the daily cap would apply per worker. The spent
tokens are shared, and so are the reservations of calls in flight: reserving checks and writes in one transaction,
so two workers can no longer both take the day's last tokens - each had reserved 700 of 1,000 and 1,400 were spent
(audit 2026-09-27, KO-06). A worker that dies with its call leaves its row behind; after ``RESERVATION_STALE_S`` it
stops counting.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS daily_tokens (day INTEGER PRIMARY KEY, used INTEGER NOT NULL);"
    "CREATE TABLE IF NOT EXISTS reservations (owner TEXT PRIMARY KEY, held INTEGER NOT NULL, updated_at REAL NOT NULL)"
)
KEEP_DAYS = 30
# A reservation lasts one LLM call, and the request deadline ends every call well within ten minutes
RESERVATION_STALE_S = 600.0
_HOLD = (
    "INSERT INTO reservations (owner, held, updated_at) VALUES (?, ?, ?) "
    "ON CONFLICT(owner) DO UPDATE SET held = excluded.held, updated_at = excluded.updated_at"
)
_HELD_ELSEWHERE = "SELECT COALESCE(SUM(held), 0) FROM reservations WHERE owner != ? AND updated_at >= ?"


class SqliteDailyStore:
    """Storage failures never stop the LLM layer: they are logged and the caller's own counter stays in charge."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5.0)

    def used(self, day: int) -> int | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute("SELECT used FROM daily_tokens WHERE day = ?", (day,)).fetchone()
        except (sqlite3.Error, OverflowError, ValueError) as exc:  # also a number SQLite cannot hold (KO-26)
            log.warning("LLM budget store not readable, counting in this process only: %s", exc)
            return None
        return int(row[0]) if row is not None else 0

    def held_elsewhere(self, owner: str, now: float) -> int | None:
        """What the other workers hold in calls in flight; ``None`` when the store cannot be read."""
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(_HELD_ELSEWHERE, (owner, now - RESERVATION_STALE_S)).fetchone()
        except (sqlite3.Error, OverflowError, ValueError) as exc:  # also a number SQLite cannot hold (KO-26)
            log.warning("LLM budget store not readable, counting in this process only: %s", exc)
            return None
        return int(row[0])

    def reserve(self, owner: str, held: int, tokens: int, day: int, limit: int, now: float) -> bool | None:
        """Grant ``tokens`` when the day's spent tokens, what the other workers hold and ``held + tokens`` fit into
        ``limit``, and record ``held + tokens`` for ``owner`` - in one transaction. ``None`` when the store fails."""
        try:
            with closing(self._connect()) as connection:
                connection.isolation_level = None  # the transaction is ours: the check and the write in one step
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute("SELECT used FROM daily_tokens WHERE day = ?", (day,)).fetchone()
                    spent = int(row[0]) if row is not None else 0
                    elsewhere = int(
                        connection.execute(_HELD_ELSEWHERE, (owner, now - RESERVATION_STALE_S)).fetchone()[0]
                    )
                    granted = spent + elsewhere + held + tokens <= limit
                    if granted:
                        connection.execute(_HOLD, (owner, held + tokens, now))
                    connection.execute("COMMIT")
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
        except (sqlite3.Error, OverflowError, ValueError) as exc:  # also a number SQLite cannot hold (KO-26)
            log.warning("LLM budget store not usable, reserving in this process only: %s", exc)
            return None
        return granted

    def settle(self, owner: str, held: int, day: int, tokens: int, now: float) -> bool:
        """Add ``tokens`` spent on ``day`` and record ``held`` as what ``owner`` still holds, in one transaction;
        ``False`` when that could not be saved."""
        try:
            with closing(self._connect()) as connection:
                if tokens:
                    connection.execute(
                        "INSERT INTO daily_tokens (day, used) VALUES (?, ?) "
                        "ON CONFLICT(day) DO UPDATE SET used = used + excluded.used",
                        (day, tokens),
                    )
                connection.execute(_HOLD, (owner, held, now))
                connection.execute("DELETE FROM daily_tokens WHERE day < ?", (day - KEEP_DAYS,))
                connection.execute("DELETE FROM reservations WHERE updated_at < ?", (now - RESERVATION_STALE_S,))
                connection.commit()
        except (sqlite3.Error, OverflowError, ValueError) as exc:  # also a number SQLite cannot hold (KO-26)
            log.warning("LLM budget store not writable, counting in this process only: %s", exc)
            return False
        return True
