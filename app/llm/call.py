"""One budgeted LLM call (PLAN.md 7): request deadline, token budget and b-api errors in one place.

Synthesis and passage selection both ask the model once per block. Whatever keeps a call from happening or
from answering becomes an ``LlmSkipped``: the block then keeps its rule-based text, and the reason goes to the
audit. A reservation is always settled, also when the call fails, so a failed call cannot shrink the day.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from app.llm.budget import RequestBudget, estimate_tokens
from app.llm.client import BApiClient, ChatResult, LlmError, Message
from app.llm.deadline import Deadline

log = logging.getLogger(__name__)

TIME_UP = "Zeitbudget der Anfrage erschöpft (REQUEST_TIMEOUT_S)"
# Who hears of every call - outcome, prompt and completion tokens: the API counts them for its metrics
# (create_app wires app.observability.metrics in). The sidecars and the CLI import this module without them: the
# metrics open files in a directory only the API's command creates (audit 2026-09-27, BE-04).
CallListener = Callable[[str, int, int], None]
_listeners: list[CallListener] = []


def listen_to_calls(listener: CallListener) -> None:
    """Have ``listener`` hear of every call from now on; the same one twice is heard once."""
    if listener not in _listeners:
        _listeners.append(listener)


def _heard(outcome: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    for listener in _listeners:
        listener(outcome, prompt_tokens, completion_tokens)


@dataclass(frozen=True)
class LlmSkipped:
    """The block keeps its rule-based text; ``reason`` goes to the audit, tokens of a failed call too."""

    reason: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def after(cls, reason: str, answer: ChatResult) -> LlmSkipped:
        """Skipped although the model answered: the call and its tokens count."""
        return cls(
            reason,
            calls=1,
            prompt_tokens=answer.prompt_tokens,
            completion_tokens=answer.completion_tokens,
            total_tokens=answer.total_tokens,
        )


def budgeted_chat(
    client: BApiClient,
    messages: Sequence[Message],
    *,
    max_output_tokens: int,
    budget: RequestBudget,
    what: str,
    deadline: Deadline | None = None,
    caller_text: str = "",
) -> ChatResult | LlmSkipped:
    """Reserve the estimated tokens, call within the time left, settle the real cost; ``what`` names the block.

    ``caller_text`` is the part of the prompt a caller shapes, reserved by its UTF-8 bytes: the estimate took random
    signs, Latin-1 or combining marks for 2.05 to 4.30 times fewer tokens than gpt-6-luna counted on 2026-09-28, and a
    request spent past its cap (audit 2026-09-28, SE-20). A token of byte-level BPE holds a byte at least; the same
    texts came to 0.38 to 0.96 tokens per byte, German prose to 0.23.

    ``max_output_tokens`` is the length of the answer; the reservation and the call add the room a reasoning model
    needs to think (``BApiClient.completion_limit``). Calls of one request run in parallel and reserve far more than
    they spend (M13): one the request budget turns away waits for the others to settle while it could still start in
    time (``Deadline.wait_s``; without a deadline while they are in flight).
    """
    limit = client.completion_limit(max_output_tokens)
    prompt_tokens = estimate_tokens("".join(m["content"] for m in messages))
    if caller_text:
        prompt_tokens += max(0, len(caller_text.encode("utf-8")) - estimate_tokens(caller_text))
    needed = prompt_tokens + limit
    if deadline is not None and deadline.call_timeout(client.timeout_s) is None:
        _heard("skipped")
        return LlmSkipped(TIME_UP)
    denial = budget.reserve(needed, wait_s=deadline.wait_s() if deadline is not None else None)
    if denial is not None:
        _heard("skipped")
        return LlmSkipped(denial)
    spent = 0
    try:
        timeout_s: float | None = None
        if deadline is not None:
            timeout_s = deadline.call_timeout(client.timeout_s)  # what the wait for the budget left
            if timeout_s is None:
                _heard("skipped")
                return LlmSkipped(TIME_UP)
        answer = client.chat(messages, max_output_tokens=limit, timeout_s=timeout_s)
        if answer.reached_before:
            # an attempt that reached the model before this answer may have cost its prompt too; only a call that
            # failed as a whole counted it (audit 2026-09-28, KO-27)
            earlier = prompt_tokens * answer.reached_before
            answer = replace(
                answer, prompt_tokens=answer.prompt_tokens + earlier, total_tokens=answer.total_tokens + earlier
            )
        spent = answer.total_tokens
    except LlmError as exc:
        log.warning("LLM call for %s failed: %s", what, exc)
        # An attempt that may have reached the model may have cost its prompt: a timeout or a 502/504 counted no
        # token before, however often it happened (audit 2026-09-27, KO-06)
        spent = prompt_tokens * exc.reached
        _heard("failed", prompt_tokens=spent)
        return LlmSkipped(f"b-api: {exc}", calls=1, prompt_tokens=spent, total_tokens=spent)
    finally:
        budget.settle(needed, spent)  # also on unexpected errors and late starts: a leaked reservation shrinks the day
    _heard("answered", prompt_tokens=answer.prompt_tokens, completion_tokens=answer.completion_tokens)
    return answer


def skipped_on_error[T, R](fn: Callable[[T], R], what: Callable[[T], str]) -> Callable[[T], R | LlmSkipped]:
    """``fn``, with an unexpected error logged and turned into an ``LlmSkipped``: the LLM layer must never break the
    rule-based path (PLAN.md 4.7). ``what`` names the item in the log line."""

    def guarded(item: T) -> R | LlmSkipped:
        try:
            return fn(item)
        except Exception as exc:
            log.exception("%s failed unexpectedly", what(item))
            return LlmSkipped(f"unerwarteter Fehler ({type(exc).__name__})")

    return guarded
