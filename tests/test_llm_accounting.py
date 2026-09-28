"""What an answer of the b-api costs, counted right whatever it holds (audit 2026-09-28, BE-14, KO-25, KO-26 and KO-27).

A gateway that passes an outage on as HTTP 500 was asked on every call: 500 neither was retried nor counted towards
the breaker, and it reset the failures in a row. An attempt that reached the model before the answer that came was not
paid for. A usage of 2^63 tokens raised out of the budget store and left the request's reservation standing. A model's
number behind a control sign and a selection nested too deep turned a request into a 500.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.article_choice import read_number
from app.llm.budget import TokenBudget, estimate_tokens
from app.llm.budget_store import SqliteDailyStore
from app.llm.call import budgeted_chat
from app.llm.client import ChatResult, LlmError
from app.synthesis.selection import parse_selection
from tests.test_llm_client import MESSAGES, FakeBApi, completion, make_client
from tests.test_llm_resilience import Clock, client_for

PROMPT = estimate_tokens("".join(message["content"] for message in MESSAGES))


def test_a_b_api_answering_500_opens_the_breaker_as_503_does() -> None:
    fake = FakeBApi(statuses=[500, 500, 500])
    client = client_for(fake, Clock())

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)
    with pytest.raises(LlmError, match="ausgesetzt"):
        client.chat(MESSAGES, max_output_tokens=10)

    assert len(fake.requests) == 3  # three attempts, then the break; ten calls made ten requests before


def test_a_500_before_the_answer_is_tried_again() -> None:
    client = client_for(FakeBApi(statuses=[500, 200]), Clock())

    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"


@pytest.mark.parametrize(("statuses", "extra"), [([504, 200], PROMPT), ([502, 504, 200], 2 * PROMPT), ([503, 200], 0)])
def test_an_attempt_that_reached_the_model_before_the_answer_is_paid_too(statuses: list[int], extra: int) -> None:
    """Behind a 502 or 504 the gateway gave up waiting for the model, which may have read the prompt (KO-06); a 503
    turned the request away before it."""
    client, _ = make_client(FakeBApi(statuses=statuses))
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()

    answer = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")

    assert isinstance(answer, ChatResult) and answer.total_tokens == 24 + extra
    assert answer.prompt_tokens == 20 + extra and budget.used == 24 + extra


def test_a_usage_beyond_any_model_is_capped_and_the_day_goes_on(tmp_path: Path) -> None:
    client, _ = make_client(FakeBApi(raw=completion("OK", prompt_tokens=2**63, completion_tokens=2**64)))
    day = TokenBudget(per_request=10**9, daily=10**12, store=SqliteDailyStore(tmp_path / "llm_budget.db"))
    budget = day.open_request()

    answer = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")

    assert isinstance(answer, ChatResult) and answer.total_tokens < 2**31
    assert day.used_today == answer.total_tokens  # stored, not left in this worker at 10^19 until midnight


def test_the_store_answers_a_number_it_cannot_hold_with_false(tmp_path: Path) -> None:
    store = SqliteDailyStore(tmp_path / "llm_budget.db")

    assert store.settle("worker", 0, 1, 2**63, 0.0) is False
    assert store.reserve("worker", 0, 2**63, 1, 2**64, 0.0) is None  # under the limit, so SQLite has to hold it


def test_a_request_gives_its_reservation_back_when_the_day_cannot_be_settled(monkeypatch: pytest.MonkeyPatch) -> None:
    day = TokenBudget(per_request=1_000, daily=10_000)
    budget = day.open_request()
    assert budget.reserve(400) is None

    def broken(reserved: int, actual: int) -> None:
        raise OverflowError("Python int too large to convert to SQLite INTEGER")

    monkeypatch.setattr(day, "settle", broken)
    with pytest.raises(OverflowError):
        budget.settle(400, 100)

    assert budget.remaining == 900  # the call's cost counts, and the 400 it held are free again


@pytest.mark.parametrize("value", [chr(0x1C) + "2", chr(0x1F) + "2" + chr(0x1E), " 2 "])
def test_a_number_a_model_wrote_behind_a_control_sign_is_read(value: str) -> None:
    assert read_number(value) == 2  # str.strip removes U+001C to U+001F, int() refused them: a 500


def test_a_selection_nested_too_deep_is_no_selection() -> None:
    nested = '{"saetze": ' + "[" * 100_000 + "]" * 100_000 + "}"

    assert parse_selection(nested) is None
