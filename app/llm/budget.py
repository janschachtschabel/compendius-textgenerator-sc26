"""Token budget for the LLM layer (PLAN.md 7): a cap per compendium request and a daily cap for all workers.

The daily counter lives in a ``DailyStore`` (llm_budget.db in STATE_DIR); only without it does each process count
for itself.

Calls reserve their upper-bound estimate before they start and settle to the actual usage afterwards, so parallel
drafts cannot overshoot a limit between the check and the call. The estimate is far above the spend (M13: a batch of
matcher=llm reserved about 13,000 tokens and spent about 8,000), so a call the request budget turns away while other
calls of the request are in flight may wait for them to settle.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

SECONDS_PER_DAY = 86_400
CHARS_PER_TOKEN = 3  # German prose with citation markers runs at 3 to 5 characters per token; 3 is the safe side


def estimate_tokens(text: str) -> int:
    """Upper-bound estimate used before a call; the API's ``usage`` replaces it afterwards."""
    return len(text) // CHARS_PER_TOKEN + 1


class DailyStore(Protocol):
    """Spent tokens per UTC day, shared between API workers (``budget_store.SqliteDailyStore``)."""

    def used(self, day: int) -> int | None:
        """Tokens spent on that day by all workers; ``None`` when the store cannot be read."""
        ...

    def add(self, day: int, tokens: int) -> bool:
        """Add spent tokens; ``False`` when they could not be saved."""
        ...


class TokenBudget:
    """Daily token cap; resets at the UTC day boundary.

    With a ``store`` the spent tokens are shared by all API workers and survive restarts; without one (tests) the
    counter lives in this process. Reservations of calls in flight always stay in the process.
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

    @property
    def remaining_today(self) -> int:
        with self._lock:
            self._roll()
            return max(0, self.daily - self._spent() - self._reserved)

    @property
    def exhausted(self) -> bool:
        return self.remaining_today <= 0

    def reserve(self, tokens: int) -> bool:
        with self._lock:
            self._roll()
            if self._spent() + self._reserved + tokens > self.daily:
                return False
            self._reserved += tokens
            return True

    def settle(self, reserved: int, actual: int) -> None:
        with self._lock:
            self._roll()
            self._reserved = max(0, self._reserved - reserved)
            self._used += actual
            if self._store is not None and (actual or self._unsaved):
                pending = actual + self._unsaved
                self._unsaved = 0 if self._store.add(self._day, pending) else pending

    def open_request(self) -> RequestBudget:
        return RequestBudget(self, self.per_request)


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
