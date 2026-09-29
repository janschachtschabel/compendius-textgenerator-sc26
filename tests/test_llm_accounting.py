"""What an answer of the b-api costs, counted right whatever it holds (audit 2026-09-28, BE-14, KO-25, KO-26 and KO-27).

A gateway that passes an outage on as HTTP 500 was asked on every call: 500 neither was retried nor counted towards
the breaker, and it reset the failures in a row. An attempt that reached the model before the answer that came was not
paid for. A usage of 2^63 tokens raised out of the budget store and left the request's reservation standing. A model's
number behind a control sign and a selection nested too deep turned a request into a 500. The retry after an attempt
that reached the model was paid without being reserved, past the caps of the request and the day (audit 2026-09-29, L1),
and an answer that could not be read was charged nothing, not even the attempts before it (A05).
"""

from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest

from app.knowledge.article_choice import read_number
from app.llm.budget import TokenBudget, estimate_tokens
from app.llm.budget_store import SqliteDailyStore
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import MAX_USAGE, ChatResult, LlmError
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


def test_parallel_calls_retrying_after_504_keep_to_the_caps_of_the_request_and_the_day() -> None:
    """Each call reserved its prompt once and was charged it again for every attempt that reached the model: five
    parallel calls meeting 504, 504 and an answer spent 120,230 tokens of a request capped at 50,000 and of a day
    capped at 60,000 (audit 2026-09-29, L1)."""
    messages = [{"role": "system", "content": "x" * 24_000}, {"role": "user", "content": "Test"}]
    prompt = estimate_tokens("".join(message["content"] for message in messages))
    all_sent = threading.Barrier(5)  # every call holds its reservation before the first 504 comes back
    attempts: dict[str, int] = {}
    counting = threading.Lock()

    def gateway(request: httpx.Request) -> httpx.Response:
        call = threading.current_thread().name
        with counting:
            attempt = attempts[call] = attempts.get(call, 0) + 1
        if attempt == 1:
            all_sent.wait(10)
        if attempt < 3:
            return httpx.Response(504)
        return httpx.Response(200, json=completion("OK", prompt_tokens=prompt, completion_tokens=40))

    client = client_for(gateway, Clock(), timeout_s=60.0, max_concurrency=5)
    day = TokenBudget(per_request=50_000, daily=60_000)
    request = day.open_request()
    options = {"max_output_tokens": 60, "budget": request, "what": "test"}
    calls = [
        threading.Thread(target=budgeted_chat, args=(client, messages), kwargs=options, name=f"call{number}")
        for number in range(5)
    ]
    for call in calls:
        call.start()
    for call in calls:
        call.join(10)

    assert request.used <= 50_000 and day.used_today <= 60_000
    assert request.remaining == 50_000 - request.used, "every reservation, the retries' too, is settled"


def test_a_retry_the_budget_has_no_room_for_ends_the_call_charged_for_its_attempt() -> None:
    fake = FakeBApi(statuses=[504, 200])
    client, _ = make_client(fake)
    room = PROMPT + client.completion_limit(100)  # one attempt fits, its retry does not
    budget = TokenBudget(per_request=room, daily=2_000_000).open_request()

    answer = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")

    assert isinstance(answer, LlmSkipped) and "Budget der Anfrage" in answer.reason
    assert len(fake.requests) == 1 and answer.prompt_tokens == PROMPT
    assert budget.used == PROMPT and budget.remaining == room - PROMPT


def test_the_reservations_of_retries_are_given_back_when_the_call_fails() -> None:
    client, _ = make_client(FakeBApi(statuses=[504, 504, 504]))
    day = TokenBudget(per_request=20_000, daily=2_000_000)
    budget = day.open_request()

    answer = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")

    assert isinstance(answer, LlmSkipped) and answer.prompt_tokens == 3 * PROMPT
    assert budget.remaining == 20_000 - 3 * PROMPT and day.remaining_today == 2_000_000 - 3 * PROMPT


CUT_SHORT = b'{"choices": ['
NO_CHOICES = b'{"choices": []}'
WITH_USAGE = b'{"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050}}'
TOTAL_ONLY = b'{"choices": [], "usage": {"total_tokens": 321}}'
BEYOND_ANY_MODEL = b'{"choices": [], "usage": {"total_tokens": 9223372036854775808}}'


@pytest.mark.parametrize(
    ("before", "body", "charged"),
    [
        ([], CUT_SHORT, PROMPT),
        ([504], CUT_SHORT, 2 * PROMPT),
        ([], NO_CHOICES, PROMPT),
        ([504, 504], NO_CHOICES, 3 * PROMPT),
        ([504], WITH_USAGE, PROMPT + 1050),
        ([], TOTAL_ONLY, 321),
        ([], BEYOND_ANY_MODEL, MAX_USAGE),
    ],
    ids=["no json", "no json after 504", "no choices", "no choices after 504s", "usage", "total", "capped"],
)
def test_an_answer_that_cannot_be_used_is_charged_as_an_attempt_that_reached_the_model(
    before: list[int], body: bytes, charged: int
) -> None:
    """A 200 without valid JSON or without choices charged nothing, the 504 before it neither, and a usage it
    reported went unread (audit 2026-09-29, A05). The model answered: what its usage says, else its prompt."""
    answers = [httpx.Response(status) for status in before] + [httpx.Response(200, content=body)]
    client = client_for(lambda request: answers.pop(0), Clock())
    day = TokenBudget(per_request=20_000, daily=2_000_000)
    budget = day.open_request()

    answer = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")

    assert isinstance(answer, LlmSkipped) and answer.calls == 1 and answer.total_tokens == charged
    assert budget.used == charged and day.used_today == charged


def test_the_usage_of_an_answer_that_cannot_be_used_keeps_prompt_and_completion_apart() -> None:
    answers = [httpx.Response(504), httpx.Response(200, content=WITH_USAGE)]
    client = client_for(lambda request: answers.pop(0), Clock())
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()

    answer = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")

    assert isinstance(answer, LlmSkipped)
    assert (answer.prompt_tokens, answer.completion_tokens, answer.total_tokens) == (PROMPT + 1000, 50, PROMPT + 1050)


class TakenSlots:
    """The call slots of a client, taken by other calls after the first attempt for longer than the call may wait."""

    def __init__(self) -> None:
        self.free = 1

    def acquire(self, timeout: float | None = None) -> bool:
        granted, self.free = self.free > 0, max(0, self.free - 1)
        return granted

    def release(self) -> None:
        pass


def test_a_retry_without_a_free_call_slot_still_charges_the_attempt_that_reached_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error of a full queue carried no attempts, so the 504 before it cost nothing (audit 2026-09-29, A05)."""
    fake = FakeBApi(statuses=[504, 200])
    client, _ = make_client(fake)
    monkeypatch.setattr(client, "_semaphore", TakenSlots())
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()

    answer = budgeted_chat(client, MESSAGES, max_output_tokens=100, budget=budget, what="test")

    assert isinstance(answer, LlmSkipped) and "Platz" in answer.reason and len(fake.requests) == 1
    assert answer.prompt_tokens == PROMPT and budget.used == PROMPT


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
