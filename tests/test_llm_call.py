"""The budgeted LLM call shared by synthesis and selection: deadline, request budget, b-api errors."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from app.llm.budget import TokenBudget
from app.llm.call import TIME_UP, LlmSkipped, budgeted_chat
from app.llm.client import REASONING_ALLOWANCE, ChatResult
from app.llm.deadline import MIN_CALL_S, Deadline
from tests.test_llm_client import MESSAGES, FakeBApi, make_client
from tests.test_llm_deadline import Clock


def test_a_granted_call_returns_the_answer_and_settles_its_real_cost() -> None:
    client, _ = make_client(FakeBApi(lambda body: "Antwort"))
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")
    assert isinstance(result, ChatResult) and result.text == "Antwort"
    assert budget.used == result.total_tokens == 24
    assert budget.remaining == 20_000 - 24  # the reservation was replaced by the usage


def test_the_request_budget_counts_the_prompt_tokens_read_from_the_cache() -> None:
    client, _ = make_client(FakeBApi(lambda body: "Antwort", cached_tokens=15))
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    for _ in range(2):
        budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")
    assert budget.cached_tokens == 30


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


def test_a_reasoning_model_gets_room_to_think_on_top_of_the_answer() -> None:
    # Measured 2026-09-19: gpt-5.6-luna counts its thinking in max_completion_tokens and answered a block with
    # nothing (finish_reason=length) when the limit only covered the text
    fake = FakeBApi(lambda body: "Antwort")
    client, _ = make_client(fake)
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")
    assert fake.bodies[0]["max_completion_tokens"] == 100 + REASONING_ALLOWANCE


def test_a_classic_model_gets_exactly_the_answer_limit() -> None:
    fake = FakeBApi(lambda body: "Antwort")
    client, _ = make_client(fake, provider="academiccloud", model="qwen3-30b-a3b-instruct-2507")
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")
    assert fake.bodies[0]["max_tokens"] == 100


def test_the_reservation_covers_the_room_to_think() -> None:
    fake = FakeBApi()
    client, _ = make_client(fake)
    budget = TokenBudget(per_request=REASONING_ALLOWANCE, daily=2_000_000).open_request()  # the answer alone fits
    result = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")
    assert isinstance(result, LlmSkipped) and "Budget" in result.reason and fake.requests == []


ONE_AT_A_TIME = 2 * REASONING_ALLOWANCE  # a request budget with room for the reservation of one test call at a time


def held_until(release: threading.Event, started: threading.Event) -> Callable[[dict[str, Any]], str]:
    """An answer that keeps its call, and with it the reservation, in flight until ``release`` is set."""

    def responder(body: dict[str, Any]) -> str:
        started.set()
        release.wait(10)
        return "Antwort"

    return responder


def test_waiting_for_the_budget_ends_when_no_call_could_start_in_time_any_more() -> None:
    started, release = threading.Event(), threading.Event()
    fake = FakeBApi(held_until(release, started))
    client, _ = make_client(fake)
    budget = TokenBudget(per_request=ONE_AT_A_TIME, daily=2_000_000).open_request()
    first = threading.Thread(
        target=lambda: budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="erster")
    )
    first.start()
    try:
        assert started.wait(10)
        began = time.monotonic()
        deadline = Deadline(MIN_CALL_S + 0.3)  # a call may still start during the next 0.3 s
        result = budgeted_chat(
            client, MESSAGES, max_output_tokens=100, budget=budget, deadline=deadline, what="zweiter"
        )
        waited = time.monotonic() - began
    finally:
        release.set()
        first.join(10)
    assert isinstance(result, LlmSkipped) and "Budget der Anfrage" in result.reason and result.calls == 0
    assert 0.2 < waited < 3.0, "it waited for the call in flight, but not beyond the last moment to start a call"
    assert len(fake.bodies) == 1 and budget.used == 24 and budget.remaining == ONE_AT_A_TIME - 24


def test_a_call_whose_wait_for_the_budget_took_the_time_releases_its_reservation() -> None:
    clock = Clock()
    deadline = Deadline(60.0, clock=clock)
    started, release = threading.Event(), threading.Event()
    fake = FakeBApi(held_until(release, started))
    client, _ = make_client(fake)
    budget = TokenBudget(per_request=ONE_AT_A_TIME, daily=2_000_000).open_request()
    results: list[ChatResult | LlmSkipped] = []
    first = threading.Thread(
        target=lambda: budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="erster")
    )
    second = threading.Thread(
        target=lambda: results.append(
            budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, deadline=deadline, what="zweiter")
        )
    )
    first.start()
    try:
        assert started.wait(10)
        second.start()
        second.join(0.2)
        waiting = second.is_alive()
        clock.now += 58  # the first call takes the request's time; then its budget is free, but the time is up
    finally:
        release.set()
        first.join(10)
        second.join(10)
    assert waiting, "the second call waits for the first to settle"
    assert results == [LlmSkipped(TIME_UP)]
    assert len(fake.bodies) == 1 and budget.used == 24 and budget.remaining == ONE_AT_A_TIME - 24


# Combining marks, one after each "a": 4.30 tokens per estimated one at gpt-6-luna on 2026-09-28, 0.96 per byte
SHAPED = "".join(chr(0x300 + n % 0x70) if n % 2 else "a" for n in range(2_000))


def test_text_a_caller_shapes_is_reserved_by_its_bytes() -> None:
    """The estimate took random signs, Latin-1 or combining marks for 2.05 to 4.30 times fewer tokens than the b-api
    counted, so a request spent past its cap (audit 2026-09-28, SE-20). A byte-level BPE token holds a byte at least."""
    messages = [{"role": "user", "content": SHAPED}]
    size = len(SHAPED.encode("utf-8"))
    client, _ = make_client(FakeBApi(lambda body: "OK"))
    room = client.completion_limit(100)

    def call(per_request: int, **kwargs: Any) -> Any:
        budget = TokenBudget(per_request=per_request, daily=2_000_000).open_request()
        return budgeted_chat(client, messages, max_output_tokens=100, budget=budget, what="test", **kwargs)

    assert isinstance(call(size + room - 1), ChatResult)  # the estimate alone takes it for far less
    assert isinstance(call(size + room - 1, caller_text=SHAPED), LlmSkipped)
    assert isinstance(call(size + room, caller_text=SHAPED), ChatResult)


def test_every_call_with_a_callers_text_reserves_it_by_its_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.knowledge import entities_llm
    from app.llm.budget import TokenBudget as Budget
    from app.synthesis import qa

    seen: list[str] = []

    def record(*args: Any, caller_text: str = "", **kwargs: Any) -> LlmSkipped:
        seen.append(caller_text)
        return LlmSkipped("recorded")

    monkeypatch.setattr(entities_llm, "budgeted_chat", record)
    monkeypatch.setattr(qa, "budgeted_chat", record)
    client, _ = make_client(FakeBApi())
    job = entities_llm.EntityLlmJob(client=client, budget=Budget(per_request=10_000, daily=100_000).open_request())

    entities_llm.named_mentions(job, SHAPED, entities_llm.EntitiesLlmReport())
    entities_llm.grade_links(job, SHAPED, [], entities_llm.EntitiesLlmReport())
    qa.LlmQaWriter(client).pairs(SHAPED, count=3, max_answer_length=300, budget=job.budget)

    assert seen == [SHAPED, SHAPED, SHAPED]


def test_the_longest_text_a_caller_may_send_still_fits_the_cap_of_balanced() -> None:
    """German prose came to 0.23 tokens per byte: reserved by its bytes, the 50,000 characters /entities takes and the
    room for 200 entities stay under the 60,000 tokens of a request in llm-free and balanced."""
    from app.api.v2.entities_schemas import MAX_TEXT_CHARS
    from app.knowledge.entities_llm import EXTRACTION_OUTPUT_TOKENS, EXTRACTION_TOKENS_PER_ENTITY
    from app.llm.prompts import get_prompt

    prose = ("Die Optik ist die Lehre vom Licht, über Linsen, Spiegel und die Brechung an Wasserflächen. " * 600)[
        :MAX_TEXT_CHARS
    ]
    client, _ = make_client(FakeBApi(lambda body: "OK"))
    budget = TokenBudget(per_request=60_000, daily=2_000_000).open_request()

    answer = budgeted_chat(
        client,
        get_prompt("entity_extraction").render(text=prose),
        max_output_tokens=max(EXTRACTION_OUTPUT_TOKENS, EXTRACTION_TOKENS_PER_ENTITY * 200),
        budget=budget,
        what="test",
        caller_text=prose,
    )

    assert isinstance(answer, ChatResult)
