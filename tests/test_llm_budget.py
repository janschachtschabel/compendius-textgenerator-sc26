"""Token budget: reservations against the limit of a request, token estimate. The daily cap is gone (D104)."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.llm.budget import RequestBudget, TokenBudget, estimate_tokens
from app.main import warn_about_removed_settings


def test_request_budget_caps_one_compendium_and_settles_to_the_actual_usage() -> None:
    budget = TokenBudget(per_request=1000)
    request = budget.open_request()
    assert isinstance(request, RequestBudget)
    assert request.reserve(600) is None
    request.settle(600, 450)
    assert request.used == 450 and request.remaining == 550
    denial = request.reserve(600)
    assert denial is not None and "Anfrage" in denial and "550" in denial
    assert request.reserve(550) is None


def test_a_request_may_open_with_a_limit_of_its_own() -> None:
    """The best-quality profiles spend more per request than the others (D59)."""
    budget = TokenBudget(per_request=1000)
    assert budget.open_request().limit == 1000
    larger = budget.open_request(2500)
    assert larger.limit == 2500 and larger.reserve(2000) is None
    assert budget.open_request().reserve(2000) is not None


def test_reservations_count_until_they_are_settled_or_released() -> None:
    request = TokenBudget(per_request=1000).open_request()
    assert request.reserve(600) is None
    assert request.reserve(600) is not None, "a second parallel draft must not overshoot the limit"
    request.release(600)  # the call failed and cost nothing
    assert request.used == 0 and request.remaining == 1000
    assert request.reserve(600) is None


def test_parallel_reservations_never_exceed_the_limit() -> None:
    """Measured by the review: check-then-act let four parallel drafts spend 20,000 tokens on a 6,000 budget."""
    request = TokenBudget(per_request=6000).open_request()
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
    request = TokenBudget(per_request=1000).open_request()
    assert request.reserve(600) is None  # a call in flight
    waiting, result = reserve_in_thread(request, 600, wait_s=10)
    waiting.join(0.2)
    assert waiting.is_alive() and result == [], "600 more do not fit next to the 600 in flight"
    request.settle(600, 300)  # the call in flight spent less than it reserved
    waiting.join(5)
    assert result == [None] and request.used == 300 and request.remaining == 100


def test_the_wait_ends_as_soon_as_no_settlement_can_make_room() -> None:
    request = TokenBudget(per_request=1000).open_request()
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
    request = TokenBudget(per_request=1000).open_request()
    assert request.reserve(600) is None  # a call in flight that does not settle in time
    began = time.monotonic()
    denial = request.reserve(600, wait_s=0.2)
    assert denial is not None and "Anfrage" in denial
    assert 0.15 < time.monotonic() - began < 2.0


def test_waiting_reservations_take_turns_within_the_limit() -> None:
    request = TokenBudget(per_request=6000).open_request()
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


@pytest.mark.parametrize(
    ("text", "characters_per_token"),
    [
        ("Licht wird an der Grenzfläche zweier Medien gebrochen. " * 40, 4.62),
        ("Свет преломляется на границе двух сред. " * 40, 3.96),
        ("ينكسر الضوء عند الحد الفاصل بين وسطين. " * 40, 3.27),
        ("光在两种介质的界面上发生折射。" * 80, 1.28),
    ],
    ids=["german", "russian", "arabic", "chinese"],
)
def test_the_estimate_stays_above_what_the_model_counts(text: str, characters_per_token: float) -> None:
    """Rates measured on 2026-09-27 with gpt-6-luna through the b-api, about 2,400 characters each. Three characters
    per token held for German, Russian and Arabic; Chinese needs more than twice that (audit 2026-09-27, SE-14)."""
    assert estimate_tokens(text) >= len(text) / characters_per_token


def test_requests_share_no_cap_beyond_their_own() -> None:
    """Jan, 2026-10-14 (D104): the b-api sets the limits per key and switches the LLM off when one is reached, so the
    service keeps only the cap of a request. Fifty requests spend what each may."""
    budget = TokenBudget(per_request=10_000)

    for _ in range(50):
        request = budget.open_request()
        assert request.reserve(9_000) is None
        request.settle(9_000, 8_000)

    denial = budget.open_request().reserve(10_001)
    assert denial is not None and "Anfrage" in denial


def test_a_leftover_daily_budget_is_named_at_start(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """D104 removed LLM_DAILY_TOKEN_BUDGET; unknown names are ignored, so a value left in an environment would change
    nothing without a word."""
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "2000000")

    with caplog.at_level(logging.WARNING):
        warn_about_removed_settings()

    assert "LLM_DAILY_TOKEN_BUDGET" in caplog.text and "D104" in caplog.text and "b-api" in caplog.text
