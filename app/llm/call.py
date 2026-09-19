"""One budgeted LLM call (PLAN.md 7): request deadline, token budget and b-api errors in one place.

Synthesis and passage selection both ask the model once per block. Whatever keeps a call from happening or
from answering becomes an ``LlmSkipped``: the block then keeps its rule-based text, and the reason goes to the
audit. A reservation is always settled, also when the call fails, so a failed call cannot shrink the day.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.llm.budget import RequestBudget, estimate_tokens
from app.llm.client import BApiClient, ChatResult, LlmError, Message
from app.llm.deadline import Deadline

log = logging.getLogger(__name__)

TIME_UP = "Zeitbudget der Anfrage erschöpft (REQUEST_TIMEOUT_S)"


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
) -> ChatResult | LlmSkipped:
    """Reserve the estimated tokens, call within the time left, settle the real cost; ``what`` names the block.

    ``max_output_tokens`` is the length of the answer; the reservation and the call add the room a reasoning model
    needs to think (``BApiClient.completion_limit``).
    """
    limit = client.completion_limit(max_output_tokens)
    needed = estimate_tokens("".join(m["content"] for m in messages)) + limit
    timeout_s: float | None = None
    if deadline is not None:
        timeout_s = deadline.call_timeout(client.timeout_s)
        if timeout_s is None:
            return LlmSkipped(TIME_UP)
    denial = budget.reserve(needed)
    if denial is not None:
        return LlmSkipped(denial)
    spent = 0
    try:
        answer = client.chat(messages, max_output_tokens=limit, timeout_s=timeout_s)
        spent = answer.total_tokens
    except LlmError as exc:
        log.warning("LLM call for %s failed: %s", what, exc)
        return LlmSkipped(f"b-api: {exc}", calls=1)
    finally:
        budget.settle(needed, spent)  # also on unexpected errors: a leaked reservation would shrink the day
    return answer
