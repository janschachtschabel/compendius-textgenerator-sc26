"""What LLM calls cost, for the audit of every step that makes them (audit 2026-09-27, WA-03).

Nine report types kept the same counters, three of them with their own copy and their own adding; ``Tokens`` holds
them and adds a call's cost once for all. ``Usage`` is the report of a step whose answering call names its model and
prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.llm.call import LlmSkipped
from app.llm.client import ChatResult


class Cost(Protocol):
    """Anything that carries the tokens of a call: an answer, a skipped call, a chosen excerpt, a drafted block."""

    @property
    def prompt_tokens(self) -> int: ...

    @property
    def completion_tokens(self) -> int: ...

    @property
    def total_tokens(self) -> int: ...


@dataclass
class Tokens:
    """How many calls a step made - skipped ones included - and their tokens."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None  # the model of the call that answered last

    def add(self, cost: Cost, calls: int = 1) -> None:
        self.calls += calls
        self.prompt_tokens += cost.prompt_tokens
        self.completion_tokens += cost.completion_tokens
        self.total_tokens += cost.total_tokens


@dataclass
class Usage(Tokens):
    """The calls and tokens of one LLM step, and the model and prompt of the call that answered."""

    prompts: list[str] = field(default_factory=list)

    def count(self, answer: ChatResult | LlmSkipped, prompt_tag: str) -> None:
        """Add the cost of a call; a call that answered also names its model and prompt."""
        self.add(answer, answer.calls if isinstance(answer, LlmSkipped) else 1)
        if isinstance(answer, ChatResult):
            self.model = answer.model
            self.prompts = [prompt_tag]
