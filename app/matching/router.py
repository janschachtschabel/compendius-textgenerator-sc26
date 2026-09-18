"""LLM router for doubtful slot assignments (PLAN.md 4.4 stage 3, 7): one budgeted call per compendium.

The policy reports close calls (``AssignmentResult.doubtful``); the router asks the model to pick one of the
candidate slots for each of them and returns overrides the policy applies in a second pass. Answers that name
a slot outside the offered candidates are ignored, so the model can never invent an assignment.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.domain.models import Chunk
from app.llm.budget import RequestBudget, estimate_tokens
from app.llm.client import BApiClient, LlmError
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.matching.policy import Doubt
from app.templates.schema import Template

log = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 600
DEFAULT_MAX_CHUNKS = 12
MAX_OUTPUT_TOKENS = 400


@dataclass
class RoutingResult:
    overrides: dict[str, str] = field(default_factory=dict)  # chunk id -> slot id
    considered: int = 0
    routed: int = 0  # valid decisions
    moved: int = 0  # decisions that differ from the policy's first choice
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    skipped: str | None = None


def parse_decisions(text: str) -> dict[str, str]:
    """The JSON object in the answer, tolerating text around it; anything unparsable yields no decisions."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


class LlmRouter:
    def __init__(self, client: BApiClient, *, max_chunks: int = DEFAULT_MAX_CHUNKS) -> None:
        self.client = client
        self.max_chunks = max_chunks

    def route(
        self,
        doubts: Sequence[Doubt],
        chunks: Mapping[str, Chunk],
        template: Template,
        budget: RequestBudget,
        deadline: Deadline | None = None,
    ) -> RoutingResult:
        """Decide the closest calls first, at most ``max_chunks`` of them, in a single request."""
        ordered = [d for d in sorted(doubts, key=lambda d: d.margin) if d.chunk_id in chunks][: self.max_chunks]
        if not ordered:
            return RoutingResult()
        slot_lines = "\n".join(f"- {slot.id}: {slot.title} — {slot.description}" for slot in template.content_slots())
        chunk_lines = []
        for doubt in ordered:
            chunk = chunks[doubt.chunk_id]
            text = re.sub(r"\s+", " ", chunk.text).strip()[:MAX_CHUNK_CHARS]
            options = ", ".join(slot_id for slot_id, _ in doubt.candidates)
            chunk_lines.append(
                f"- {doubt.chunk_id} (Überschrift: {chunk.full_heading}; mögliche Bausteine: {options}): {text}"
            )
        messages = get_prompt("slot_router").render(slots=slot_lines, chunks="\n".join(chunk_lines))
        result = RoutingResult(considered=len(ordered))

        needed = estimate_tokens(messages[0]["content"] + messages[1]["content"]) + MAX_OUTPUT_TOKENS
        timeout_s: float | None = None
        if deadline is not None:
            timeout_s = deadline.call_timeout(self.client.timeout_s)
            if timeout_s is None:
                result.skipped = "Zeitbudget der Anfrage erschöpft (REQUEST_TIMEOUT_S)"
                return result
        result.skipped = budget.reserve(needed)
        if result.skipped is not None:
            return result
        result.calls = 1
        spent = 0
        try:
            answer = self.client.chat(messages, max_output_tokens=MAX_OUTPUT_TOKENS, timeout_s=timeout_s)
            spent = answer.total_tokens
        except LlmError as exc:
            log.warning("LLM router failed: %s", exc)
            result.skipped = f"b-api: {exc}"
            return result
        finally:
            budget.settle(needed, spent)
        result.prompt_tokens, result.completion_tokens = answer.prompt_tokens, answer.completion_tokens
        result.total_tokens = answer.total_tokens

        allowed = {doubt.chunk_id: {slot_id for slot_id, _ in doubt.candidates} for doubt in ordered}
        for chunk_id, slot_id in parse_decisions(answer.text).items():
            if slot_id in allowed.get(chunk_id, set()):
                result.overrides[chunk_id] = slot_id
        result.routed = len(result.overrides)
        first_choice = {doubt.chunk_id: doubt.candidates[0][0] for doubt in ordered}
        result.moved = sum(1 for chunk_id, slot_id in result.overrides.items() if first_choice[chunk_id] != slot_id)
        return result
