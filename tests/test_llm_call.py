"""The budgeted LLM call shared by synthesis and selection: deadline, request budget, b-api errors."""

from __future__ import annotations

from app.llm.budget import TokenBudget
from app.llm.call import TIME_UP, LlmSkipped, budgeted_chat
from app.llm.client import ChatResult
from app.llm.deadline import Deadline
from tests.test_llm_client import MESSAGES, FakeBApi, make_client


def test_a_granted_call_returns_the_answer_and_settles_its_real_cost() -> None:
    client, _ = make_client(FakeBApi(lambda body: "Antwort"))
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")
    assert isinstance(result, ChatResult) and result.text == "Antwort"
    assert budget.used == result.total_tokens == 24
    assert budget.remaining == 20_000 - 24  # the reservation was replaced by the usage


def test_no_call_starts_when_the_request_has_no_time_left() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake)
    deadline = Deadline(1.0)  # below the minimum a call needs
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, deadline=deadline, what="test")
    assert result == LlmSkipped(TIME_UP)
    assert fake.requests == [] and budget.used == 0


def test_a_denied_budget_skips_the_call_with_the_reason() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake)
    budget = TokenBudget(per_request=50, daily=2_000_000).open_request()
    result = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")
    assert isinstance(result, LlmSkipped) and "Budget" in result.reason and result.calls == 0
    assert fake.requests == []


def test_a_b_api_error_counts_one_call_and_releases_the_reservation() -> None:
    client, _ = make_client(FakeBApi(statuses=[400]))
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")
    assert isinstance(result, LlmSkipped) and result.reason.startswith("b-api:") and result.calls == 1
    assert budget.used == 0 and budget.remaining == 20_000


def test_skipped_after_an_answer_carries_the_tokens_of_that_call() -> None:
    answer = ChatResult(
        text="", model="m", prompt_tokens=10, completion_tokens=5, total_tokens=15, finish_reason="stop"
    )
    skipped = LlmSkipped.after("leer", answer)
    assert skipped == LlmSkipped("leer", calls=1, prompt_tokens=10, completion_tokens=5, total_tokens=15)
