"""The b-api client under failure: one deadline for all attempts, a breaker that also sees 429 and 5xx, a single
probe after the break, a refused key or model that stops the LLM for a while, and the cost of a failed call that
reached the model (audit 2026-09-27, KO-04, KO-05, BE-04, KO-06, SE-10)."""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx
import pytest

from app.llm.budget import TokenBudget, estimate_tokens
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import AUTH_SUSPEND_S, BREAKER_S, BApiClient, LlmError
from app.llm.gateway import LlmGateway, LlmOptions
from tests.test_llm_client import BASE, KEY, MESSAGES, FakeBApi


class Clock:
    """Fake monotonic time; the b-api takes ``request_s`` per request, a sleep advances it as well."""

    def __init__(self, request_s: float = 0.0) -> None:
        self.now = 1000.0
        self.request_s = request_s
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def client_for(fake: Any, clock: Clock, **kwargs: Any) -> BApiClient:
    def slow(request: httpx.Request) -> httpx.Response:
        clock.now += clock.request_s
        return fake(request)  # type: ignore[no-any-return]

    options: dict[str, Any] = {"provider": "openai", "model": "gpt-6-luna", "timeout_s": 30.0, "jitter": lambda: 0.5}
    options.update(kwargs)
    return BApiClient(BASE, KEY, transport=httpx.MockTransport(slow), clock=clock, sleep=clock.sleep, **options)


def test_one_deadline_covers_every_attempt() -> None:
    """Each retry got the full limit again: a call with a 5.5 s deadline against a 503 after 2.2 s took 6.6 s."""
    clock = Clock(request_s=2.2)
    fake = FakeBApi(statuses=[503, 503, 200])
    client = client_for(fake, clock)

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10, timeout_s=5.5)

    assert clock.now - 1000.0 <= 5.5
    assert len(fake.requests) == 1  # 3.3 s were left after the backoff: too little to start another call


def test_a_retry_gets_the_time_that_is_left() -> None:
    clock = Clock(request_s=2.2)
    fake = FakeBApi(statuses=[503, 200])
    client = client_for(fake, clock)

    assert client.chat(MESSAGES, max_output_tokens=10, timeout_s=20.0).text == "OK"

    first, second = (request.extensions["timeout"]["read"] for request in fake.requests)
    assert first == pytest.approx(20.0)
    assert second == pytest.approx(20.0 - 2.2 - 1.5)


def test_the_breaker_opens_after_a_call_that_met_only_503() -> None:
    """Only a connection failure tripped it: a gateway answering 503 to everything got three attempts per call."""
    fake = FakeBApi(statuses=[503, 503, 503])
    client = client_for(fake, Clock())
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    with pytest.raises(LlmError, match="ausgesetzt"):
        client.chat(MESSAGES, max_output_tokens=10)

    assert len(fake.requests) == 3


@pytest.mark.parametrize(("draw", "sleeps"), [(0.0, [0.75, 1.5]), (0.5, [1.5, 3.0]), (1.0, [2.25, 4.5])])
def test_the_backoff_is_spread_around_its_value(draw: float, sleeps: list[float]) -> None:
    clock = Clock()
    client = client_for(FakeBApi(statuses=[503, 503, 200]), clock, jitter=lambda: draw)

    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"

    assert clock.sleeps == sleeps


def retry_after(seconds: str, then: int = 200) -> Any:
    """A b-api that answers 429 with Retry-After once, then ``then``."""
    answers = iter([httpx.Response(429, headers={"Retry-After": seconds}, json={"error": "slow down"})])
    fallback = FakeBApi(statuses=[then])

    def answer(request: httpx.Request) -> httpx.Response:
        return next(answers, None) or fallback(request)

    return answer


def test_retry_after_is_honoured_within_the_deadline() -> None:
    clock = Clock()
    client = client_for(retry_after("7"), clock)

    assert client.chat(MESSAGES, max_output_tokens=10, timeout_s=30.0).text == "OK"

    assert clock.sleeps == [7.0]


def test_a_retry_after_beyond_the_deadline_ends_the_call_at_once() -> None:
    clock = Clock()
    client = client_for(retry_after("120"), clock)

    with pytest.raises(LlmError) as failed:
        client.chat(MESSAGES, max_output_tokens=10, timeout_s=30.0)

    assert failed.value.status == 429 and clock.sleeps == []


def test_after_the_break_one_call_probes_while_the_others_fail_fast() -> None:
    """All calls waiting for the breaker used to start at once when it closed."""
    clock = Clock()
    gate, probing = threading.Event(), threading.Event()
    fake = FakeBApi(transport_failures=3)
    held = {"on": False}

    def answer(request: httpx.Request) -> httpx.Response:
        if held["on"]:
            probing.set()
            gate.wait(5)
        return fake(request)

    client = client_for(answer, clock)
    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)
    clock.now += BREAKER_S + 1
    held["on"] = True
    answers: dict[str, str] = {}
    probe = threading.Thread(target=lambda: answers.update(probe=client.chat(MESSAGES, max_output_tokens=10).text))
    probe.start()
    assert probing.wait(5)

    with pytest.raises(LlmError, match="ausgesetzt"):
        client.chat(MESSAGES, max_output_tokens=10)
    gate.set()
    probe.join(5)
    held["on"] = False

    assert answers == {"probe": "OK"}
    assert client.chat(MESSAGES, max_output_tokens=10).text == "OK"  # the probe closed the breaker


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_refused_key_or_model_suspends_the_llm_and_says_why(status: int) -> None:
    """401, 403 and 404 changed no state: /health reported the LLM available while every call failed (BE-04)."""
    clock = Clock()
    fake = FakeBApi(statuses=[status])
    client = client_for(fake, clock)
    gateway = LlmGateway(client, TokenBudget(per_request=20_000, daily=2_000_000), LlmOptions(), clock=clock)
    assert gateway.available

    with pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert not gateway.available
    assert f"HTTP {status}" in gateway.unavailable_reason and "ausgesetzt" in gateway.unavailable_reason
    assert not gateway.status()["available"]
    clock.now += AUTH_SUSPEND_S + 1
    assert gateway.available


def test_an_echoed_key_leaves_no_prefix_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """The error body was cut to 200 characters before the key was blanked: a key across the cut kept its start."""
    echo = "x" * 195 + KEY

    client = client_for(lambda request: httpx.Response(400, text=echo), Clock())
    with caplog.at_level(logging.WARNING), pytest.raises(LlmError):
        client.chat(MESSAGES, max_output_tokens=10)

    assert "HTTP 400" in caplog.text
    assert KEY[:5] not in caplog.text


PROMPT = [{"role": "user", "content": "Licht wird an der Grenze zweier Medien gebrochen. " * 40}]


@pytest.mark.parametrize(
    ("error", "charged"),
    [(httpx.ReadTimeout("slow"), True), (httpx.ConnectError("refused"), False)],
    ids=["timed out after sending", "never reached the gateway"],
)
def test_a_failed_call_that_reached_the_model_charges_its_prompt(error: Exception, charged: bool) -> None:
    """A timeout or a 502/504 counted no token, though the model may have read the prompt (KO-06)."""
    fake = FakeBApi(transport_failures=3, transport_error=error)
    budget = TokenBudget(per_request=100_000, daily=1_000_000)

    answer = budgeted_chat(
        client_for(fake, Clock()), PROMPT, max_output_tokens=10, budget=budget.open_request(), what="Probe"
    )

    assert isinstance(answer, LlmSkipped)
    prompt_tokens = estimate_tokens(PROMPT[0]["content"])
    assert budget.used_today == (prompt_tokens if charged else 0)
    assert answer.prompt_tokens == (prompt_tokens if charged else 0)


def test_every_attempt_that_met_a_504_charges_the_prompt() -> None:
    """Behind a 504 the model may have read the prompt each time; a 503 or 429 turned the request away (KO-06)."""
    fake = FakeBApi(statuses=[504, 503, 504])
    budget = TokenBudget(per_request=100_000, daily=1_000_000)

    budgeted_chat(client_for(fake, Clock()), PROMPT, max_output_tokens=10, budget=budget.open_request(), what="Probe")

    assert budget.used_today == 2 * estimate_tokens(PROMPT[0]["content"])
