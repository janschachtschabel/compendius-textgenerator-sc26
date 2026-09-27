"""Token budget for the LLM layer (PLAN.md 7): a cap per compendium request and a daily cap for all workers.

The daily counter lives in a ``DailyStore`` (llm_budget.db in STATE_DIR); only without it does each process count
for itself.

Calls reserve their upper-bound estimate before they start and settle to the actual usage afterwards, so parallel
drafts cannot overshoot a limit between the check and the call. The estimate is far above the spend (M13: a batch of
matcher=llm reserved about 13,000 tokens and spent about 8,000), so a call the request budget turns away while other
calls of the request are in flight may wait for them to settle.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from typing import Protocol

SECONDS_PER_DAY = 86_400
CHARS_PER_TOKEN = 3  # German prose with citation markers runs at 3 to 5 characters per token; 3 is the safe side
# From U+0800 on - Chinese, Japanese, Korean, but also the typographic quotes and dashes - a character counts as a
# token of its own
_WIDE = re.compile(f"[{chr(0x800)}-{chr(0x10FFFF)}]")


def estimate_tokens(text: str) -> int:
    """Upper-bound estimate used before a call; the API's ``usage`` replaces it afterwards.

    Measured on 2026-09-27 with gpt-6-luna through the b-api, about 2,400 characters each: German 4.62 characters
    per token, Russian 3.96, Arabic 3.27 - three per token is the safe side for all of them -, but Chinese 1.28:
    three per token undercounted it by a factor of 2.35, and a caller's Chinese text could spend a multiple of its
    reservation (audit 2026-09-27, SE-14). Counted as a token each, Chinese comes out 1.28 times its real count.
    """
    _, wide = _WIDE.subn("", text)
    return (len(text) - wide) // CHARS_PER_TOKEN + wide + 1


class DailyStore(Protocol):
    """Spent tokens per UTC day and the reservations of calls in flight, shared between API workers
    (``budget_store.SqliteDailyStore``). ``owner`` names one worker's budget."""

    def used(self, day: int) -> int | None:
        """Tokens spent on that day by all workers; ``None`` when the store cannot be read."""
        ...

    def held_elsewhere(self, owner: str, now: float) -> int | None:
        """What the other workers hold in calls in flight; ``None`` when the store cannot be read."""
        ...

    def reserve(self, owner: str, held: int, tokens: int, day: int, limit: int, now: float) -> bool | None:
        """Grant ``tokens`` when spent, held elsewhere and ``held + tokens`` fit into ``limit``, and record
        ``held + tokens`` for ``owner``, in one step for all workers; ``None`` when the store cannot decide."""
        ...

    def settle(self, owner: str, held: int, day: int, tokens: int, now: float) -> bool:
        """Add ``tokens`` spent on ``day`` and record ``held`` for ``owner``; ``False`` when not saved."""
        ...


class TokenBudget:
    """Daily token cap; resets at the UTC day boundary.

    With a ``store`` the spent tokens and the reservations of calls in flight are shared by all API workers, and the
    spent tokens survive restarts; without one (tests), or while it fails, the process counts for itself.
    """

    def __init__(
        self,
        per_request: int,
        daily: int,
        clock: Callable[[], float] = time.time,
        store: DailyStore | None = None,
    ) -> None:
        self.per_request = per_request
        self.daily = daily
        self._clock = clock
        self._store = store
        self._lock = threading.Lock()
        self._day = self._today()
        self._used = 0
        self._reserved = 0
        self._unsaved = 0  # spent during a store outage; written with the next successful update
        self._owner = uuid.uuid4().hex  # this process's row among the reservations of all workers

    def _today(self) -> int:
        return int(self._clock() // SECONDS_PER_DAY)

    def _roll(self) -> None:
        day = self._today()
        if day != self._day:
            # Reservations of calls in flight carry over and settle into the new day.
            self._day, self._used, self._unsaved = day, 0, 0

    def _spent(self) -> int:
        """Spent today; the own counter is the floor when the store lags or fails (lock held by the caller)."""
        if self._store is None:
            return self._used
        stored = self._store.used(self._day)
        if stored is None:
            return self._used
        return max(self._used, stored + self._unsaved)

    @property
    def used_today(self) -> int:
        with self._lock:
            self._roll()
            return self._spent()

    def _elsewhere(self) -> int:
        """What the other workers hold in calls in flight (lock held by the caller)."""
        if self._store is None:
            return 0
        return self._store.held_elsewhere(self._owner, self._clock()) or 0

    @property
    def remaining_today(self) -> int:
        with self._lock:
            self._roll()
            return max(0, self.daily - self._spent() - self._reserved - self._elsewhere())

    @property
    def exhausted(self) -> bool:
        return self.remaining_today <= 0

    def reserve(self, tokens: int) -> bool:
        with self._lock:
            self._roll()
            if self._store is not None:
                # One step for all workers; what this process could not save yet counts against the day as well
                limit = self.daily - self._unsaved
                granted = self._store.reserve(self._owner, self._reserved, tokens, self._day, limit, self._clock())
                if granted is not None:
                    if granted:
                        self._reserved += tokens
                    return granted
            if self._spent() + self._reserved + tokens > self.daily:
                return False
            self._reserved += tokens
            return True

    def settle(self, reserved: int, actual: int) -> None:
        with self._lock:
            self._roll()
            self._reserved = max(0, self._reserved - reserved)
            self._used += actual
            if self._store is not None:
                pending = actual + self._unsaved
                saved = self._store.settle(self._owner, self._reserved, self._day, pending, self._clock())
                self._unsaved = 0 if saved else pending

    def open_request(self, limit: int | None = None) -> RequestBudget:
        """The budget of one request: ``limit`` tokens, else ``per_request`` (the best-quality profiles, D59)."""
        return RequestBudget(self, self.per_request if limit is None else limit)


class RequestBudget:
    """Budget of one compendium request; every reservation also reserves in the daily budget."""

    def __init__(self, budget: TokenBudget, limit: int) -> None:
        self.budget = budget
        self.limit = limit
        self.used = 0
        self._reserved = 0
        self._settled = threading.Condition()

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used - self._reserved)

    def reserve(self, tokens: int, wait_s: float | None = 0.0) -> str | None:
        """Reserve ``tokens`` for one call; ``None`` when granted, else the reason for the audit.

        While reservations of calls in flight stand in the way and their settling could make room, the call waits up
        to ``wait_s`` seconds for them (``None``: as long as that holds, which the calls' own timeouts bound). The
        daily budget does not wait: all requests and workers share it, and near its end a call falls back at once.
        """
        with self._settled:
            self._settled.wait_for(lambda: self._fits(tokens) or self.used + tokens > self.limit, timeout=wait_s)
            if not self._fits(tokens):
                return f"Token-Budget der Anfrage erschöpft ({tokens} Tokens nötig, {self.remaining} frei)"
            if not self.budget.reserve(tokens):
                return f"Tagesbudget erschöpft ({tokens} Tokens nötig, {self.budget.remaining_today} frei)"
            self._reserved += tokens
            return None

    def _fits(self, tokens: int) -> bool:
        return self.used + self._reserved + tokens <= self.limit

    def settle(self, reserved: int, actual: int) -> None:
        """Replace a reservation by what the call actually cost (``usage.total_tokens``); waiting calls try again."""
        self.budget.settle(reserved, actual)  # first: a call woken below finds the daily budget settled as well
        with self._settled:
            self._reserved = max(0, self._reserved - reserved)
            self.used += actual
            self._settled.notify_all()

    def release(self, reserved: int) -> None:
        """Give a reservation back: the call failed and cost nothing."""
        self.settle(reserved, 0)
