"""Time budget of one request for its LLM work (REQUEST_TIMEOUT_S): per-call timeouts shrink, late calls are skipped."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import pytest

from app.llm.budget import TokenBudget
from app.llm.call import LlmSkipped
from app.llm.client import BApiClient, LlmError
from app.llm.deadline import MIN_CALL_S, Deadline
from app.synthesis.llm import LlmSection, LlmSynthesizer
from tests.test_llm_client import BASE, KEY, MESSAGES, FakeBApi
from tests.test_llm_synthesis import ANSWER, SCORED, SOURCES, _slot


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _client(fake: FakeBApi, **kwargs: object) -> BApiClient:
    return BApiClient(
        BASE,
        KEY,
        provider="openai",
        model="gpt-5.6-luna",
        timeout_s=120.0,
        transport=httpx.MockTransport(fake),
        **kwargs,  # type: ignore[arg-type]
    )


def test_deadline_counts_down_and_caps_the_call_timeout() -> None:
    clock = Clock()
    deadline = Deadline(60.0, clock=clock)
    assert deadline.remaining() == 60.0 and deadline.call_timeout(120.0) == 60.0
    assert deadline.wait_s() == 60.0 - MIN_CALL_S, "a call that waits to start still needs MIN_CALL_S to run"
    clock.now += 50
    assert deadline.call_timeout(8.0) == 8.0 and deadline.call_timeout(120.0) == 10.0
    clock.now += 10 - MIN_CALL_S + 0.5
    assert deadline.call_timeout(120.0) is None, "too little time left to start another call"
    assert deadline.wait_s() == 0.0
    clock.now += 100
    assert deadline.remaining() == 0.0


def test_chat_uses_the_given_timeout_and_a_shortened_timeout_does_not_trip_the_breaker() -> None:
    fake = FakeBApi(transport_failures=1, transport_error=httpx.ReadTimeout("slow"))
    client = _client(fake)
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10, timeout_s=7.0)
    assert fake.requests[0].extensions["timeout"]["read"] == pytest.approx(7.0, abs=0.5)
    assert not client.suspended, "our own short deadline is no evidence of an outage"
    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"

    fake = FakeBApi(transport_failures=1, transport_error=httpx.ReadTimeout("slow"))
    client = _client(fake)
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10, timeout_s=45.0)
    assert client.suspended, "half a minute without an answer is an outage"


def test_synthesizer_shrinks_the_timeout_and_skips_when_the_time_is_up() -> None:
    clock = Clock()
    deadline = Deadline(30.0, clock=clock)
    fake = FakeBApi(lambda body: ANSWER)
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    synthesizer = LlmSynthesizer(_client(fake))
    clock.now += 18
    written = synthesizer.write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget, deadline=deadline
    )
    assert isinstance(written, LlmSection)
    assert fake.requests[0].extensions["timeout"]["read"] == pytest.approx(12.0, abs=0.5)

    clock.now += 10
    skipped = synthesizer.write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget, deadline=deadline
    )
    assert isinstance(skipped, LlmSkipped) and "Zeitbudget" in skipped.reason and skipped.calls == 0
    assert len(fake.requests) == 1 and budget.remaining == 20_000 - budget.used, "nothing stays reserved"


def test_waiting_for_a_free_call_slot_counts_against_the_timeout() -> None:
    """The semaphore wait was unbounded: under parallel requests a draft could outlive the request deadline."""
    started, release = threading.Event(), threading.Event()

    def slow(body: dict[str, Any]) -> str:
        started.set()
        release.wait(10)
        return "OK"

    fake = FakeBApi(slow)
    client = _client(fake, max_concurrency=1)
    worker = threading.Thread(target=lambda: client.chat(MESSAGES, max_output_tokens=10))
    worker.start()
    try:
        assert started.wait(10)
        began = time.monotonic()
        with pytest.raises(LlmError, match="Platz"):
            client.chat(MESSAGES, max_output_tokens=10, timeout_s=0.3)
        assert time.monotonic() - began < 3.0
        assert len(fake.requests) == 1, "the waiting call never went out"
        assert not client.suspended, "a full queue on our side is no outage of the b-api"
    finally:
        release.set()
        worker.join(10)
