"""Token budget: reservations against a per-request and a shared daily limit, UTC rollover, token estimate."""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.llm.budget import RequestBudget, TokenBudget, estimate_tokens
from app.llm.budget_store import SqliteDailyStore


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_request_budget_caps_one_compendium_and_settles_to_the_actual_usage() -> None:
    budget = TokenBudget(per_request=1000, daily=1_000_000)
    request = budget.open_request()
    assert isinstance(request, RequestBudget)
    assert request.reserve(600) is None
    request.settle(600, 450)
    assert request.used == 450 and request.remaining == 550
    denial = request.reserve(600)
    assert denial is not None and "Anfrage" in denial and "550" in denial
    assert request.reserve(550) is None


def test_reservations_count_until_they_are_settled_or_released() -> None:
    request = TokenBudget(per_request=1000, daily=10_000).open_request()
    assert request.reserve(600) is None
    assert request.reserve(600) is not None, "a second parallel draft must not overshoot the limit"
    request.release(600)  # the call failed and cost nothing
    assert request.used == 0 and request.remaining == 1000
    assert request.reserve(600) is None


def test_daily_budget_is_shared_between_requests_and_named_in_the_denial() -> None:
    budget = TokenBudget(per_request=10_000, daily=1000)
    first = budget.open_request()
    assert first.reserve(700) is None
    first.settle(700, 700)
    second = budget.open_request()
    assert budget.used_today == 700 and budget.remaining_today == 300
    denial = second.reserve(400)
    assert denial is not None and "Tagesbudget" in denial and "300" in denial
    assert second.reserve(300) is None
    second.settle(300, 300)
    assert budget.exhausted
    assert budget.open_request().reserve(1) is not None


def test_daily_budget_resets_at_the_utc_day_boundary() -> None:
    clock = Clock(now=86_400 * 20_000 + 3_600)  # one hour into a day
    budget = TokenBudget(per_request=10_000, daily=1000, clock=clock)
    request = budget.open_request()
    assert request.reserve(1000) is None
    request.settle(1000, 1000)
    assert budget.exhausted
    clock.now += 86_400
    assert not budget.exhausted and budget.used_today == 0
    assert budget.open_request().reserve(1000) is None


def test_parallel_reservations_never_exceed_the_limit() -> None:
    """Measured by the review: check-then-act let four parallel drafts spend 20,000 tokens on a 6,000 budget."""
    request = TokenBudget(per_request=6000, daily=1_000_000).open_request()
    barrier = threading.Barrier(8)

    def reserve() -> bool:
        barrier.wait()
        return request.reserve(5000) is None

    with ThreadPoolExecutor(max_workers=8) as pool:
        granted = list(pool.map(lambda _: reserve(), range(8)))
    assert sum(granted) == 1


def reserve_in_thread(
    request: RequestBudget, tokens: int, wait_s: float | None
) -> tuple[threading.Thread, list[str | None]]:
    """Reserve from another thread, as a parallel call of the same request does; the list receives the result."""
    result: list[str | None] = []
    thread = threading.Thread(target=lambda: result.append(request.reserve(tokens, wait_s=wait_s)), daemon=True)
    thread.start()
    return thread, result


def test_a_denied_reservation_waits_for_the_calls_of_the_request_in_flight() -> None:
    """M13: parallel batches of matcher=llm reserved about 13,000 tokens each and spent about 8,000, so a budget of
    60,000 turned batches away at once that the real spend had room for."""
    request = TokenBudget(per_request=1000, daily=1_000_000).open_request()
    assert request.reserve(600) is None  # a call in flight
    waiting, result = reserve_in_thread(request, 600, wait_s=10)
    waiting.join(0.2)
    assert waiting.is_alive() and result == [], "600 more do not fit next to the 600 in flight"
    request.settle(600, 300)  # the call in flight spent less than it reserved
    waiting.join(5)
    assert result == [None] and request.used == 300 and request.remaining == 100


def test_the_wait_ends_as_soon_as_no_settlement_can_make_room() -> None:
    request = TokenBudget(per_request=1000, daily=1_000_000).open_request()
    assert request.reserve(400) is None and request.reserve(400) is None  # two calls in flight
    waiting, result = reserve_in_thread(request, 500, wait_s=None)  # no time limit: the calls in flight bound it
    request.settle(400, 400)
    waiting.join(0.2)
    assert waiting.is_alive(), "400 spent and 500 wanted: the other call in flight may still leave room"
    request.settle(400, 400)
    waiting.join(5)
    assert not waiting.is_alive() and result[0] is not None and "Anfrage" in result[0]

    hopeless, result = reserve_in_thread(request, 300, wait_s=None)
    hopeless.join(1.0)
    assert not hopeless.is_alive(), "800 spent: 300 more can never fit, so there is nothing to wait for"
    assert result[0] is not None and "Anfrage" in result[0]


def test_waiting_for_the_budget_ends_after_wait_s() -> None:
    request = TokenBudget(per_request=1000, daily=1_000_000).open_request()
    assert request.reserve(600) is None  # a call in flight that does not settle in time
    began = time.monotonic()
    denial = request.reserve(600, wait_s=0.2)
    assert denial is not None and "Anfrage" in denial
    assert 0.15 < time.monotonic() - began < 2.0


def test_the_daily_budget_turns_a_call_away_without_waiting() -> None:
    """The daily cap belongs to all requests and workers; near its end a call falls back instead of queueing."""
    request = TokenBudget(per_request=10_000, daily=1000).open_request()
    assert request.reserve(700) is None
    began = time.monotonic()
    denial = request.reserve(400, wait_s=5)
    assert denial is not None and "Tagesbudget" in denial
    assert time.monotonic() - began < 1.0


def test_waiting_reservations_take_turns_within_the_limit() -> None:
    request = TokenBudget(per_request=6000, daily=1_000_000).open_request()
    barrier = threading.Barrier(8)

    def call() -> bool:
        barrier.wait()
        if request.reserve(2500, wait_s=5) is not None:
            return False
        time.sleep(0.01)
        request.settle(2500, 1000)
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        granted = sum(pool.map(lambda _: call(), range(8)))
    # Two fit at once; each settles at 1,000, and once 4,000 are spent another 2,500 can never fit
    assert granted == 4 and request.used == 4000 and request.remaining == 2000


def test_estimate_tokens_is_positive_and_grows_with_the_text() -> None:
    assert estimate_tokens("") >= 1
    short, long = estimate_tokens("Licht bricht sich."), estimate_tokens("Licht bricht sich an der Grenze. " * 20)
    assert 1 <= short < long
    assert long <= len("Licht bricht sich an der Grenze. " * 20)


def test_daily_usage_is_shared_between_workers_and_survives_a_restart(tmp_path: Path) -> None:
    """The image runs two uvicorn workers; a counter per process doubled the daily cap and forgot it on restart."""
    path = tmp_path / "llm_budget.db"
    clock = Clock(now=86_400 * 20_000 + 100)
    worker_a = TokenBudget(per_request=10_000, daily=1000, clock=clock, store=SqliteDailyStore(path))
    worker_b = TokenBudget(per_request=10_000, daily=1000, clock=clock, store=SqliteDailyStore(path))
    request = worker_a.open_request()
    assert request.reserve(700) is None
    request.settle(700, 700)
    assert worker_b.used_today == 700 and worker_b.remaining_today == 300
    denial = worker_b.open_request().reserve(400)
    assert denial is not None and "Tagesbudget" in denial

    restarted = TokenBudget(per_request=10_000, daily=1000, clock=clock, store=SqliteDailyStore(path))
    assert restarted.used_today == 700
    clock.now += 86_400
    assert restarted.used_today == 0 and worker_b.open_request().reserve(1000) is None


def test_a_failing_store_leaves_the_process_counter_in_charge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = SqliteDailyStore(tmp_path / "llm_budget.db")
    budget = TokenBudget(per_request=10_000, daily=1000, store=store)

    def locked(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "_connect", locked)
    request = budget.open_request()
    assert request.reserve(600) is None
    request.settle(600, 600)
    assert budget.used_today == 600, "the guard keeps counting in memory"
    assert budget.open_request().reserve(600) is not None
    assert "llm budget store" in caplog.text.lower()


class FlakyStore:
    """In-memory stand-in for the shared store that can be switched to failing."""

    def __init__(self) -> None:
        self.days: dict[int, int] = {}
        self.fail = False

    def used(self, day: int) -> int | None:
        return None if self.fail else self.days.get(day, 0)

    def add(self, day: int, tokens: int) -> bool:
        if self.fail:
            return False
        self.days[day] = self.days.get(day, 0) + tokens
        return True


def test_tokens_spent_during_a_store_outage_are_neither_lost_nor_hidden_by_other_workers() -> None:
    clock = Clock(now=86_400 * 20_000 + 100)
    day = 20_000
    store = FlakyStore()
    store.days[day] = 300  # another worker spent 300 today
    budget = TokenBudget(per_request=10_000, daily=1000, clock=clock, store=store)
    store.fail = True
    request = budget.open_request()
    assert request.reserve(400) is None
    request.settle(400, 400)  # cannot be saved
    store.fail = False
    assert budget.used_today == 700, "300 of the other worker plus the 400 that could not be saved"
    again = budget.open_request()
    assert again.reserve(100) is None
    again.settle(100, 100)
    assert store.days[day] == 800, "the unsaved tokens are written with the next successful update"
    assert budget.used_today == 800
    clock.now += 86_400
    assert budget.used_today == 0
