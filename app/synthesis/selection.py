"""LLM passage selection (PLAN.md 4.7, D33): the model picks a block's sentences, the wording stays the source's.

Every candidate paragraph is offered with numbered sentences ("2.3" is the third sentence of the second
paragraph). The model answers with numbers only, so it can neither invent nor rephrase text; numbers that were
not offered are ignored and counted. The chosen sentences become excerpts: copies of their chunks whose text is
just those sentences, in source order. The writer renders excerpts like any extractive block, and the LLM
generation takes them as its evidence. Lists and tables are offered and taken as a whole.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.models import Chunk, ChunkKind, ScoredChunk, Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.synthesis.citations import collapse
from app.synthesis.extractive import usable_sentences
from app.synthesis.llm import slot_prompt_fields
from app.templates.schema import TemplateSlot

MAX_CANDIDATE_CHARS = 1000  # per paragraph: complete sentences up to this length
MAX_OUTPUT_TOKENS = 800  # numbers only, but reasoning models spend part of the limit before they answer
LENGTH_FACTOR = 1.5  # a choice stops at a paragraph boundary once it holds this multiple of the target (as the policy)
MATCHER = "llm"
_KIND_NOTE = {ChunkKind.LIST: "; Liste", ChunkKind.TABLE: "; Tabelle"}


@dataclass(frozen=True)
class Selection:
    excerpts: list[ScoredChunk]  # chosen sentences per paragraph, paragraphs in the order the model named them
    sentences: int  # chosen sentences that made it into the excerpts
    offered: int  # paragraphs offered
    invalid: int  # numbers in the answer that were not offered
    cut: int  # chosen sentences left out because the choice ran far beyond the target length
    prompt: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def numbered_sentences(chunk: Chunk) -> list[str]:
    """What the model may choose from a paragraph: its usable sentences up to ``MAX_CANDIDATE_CHARS``.

    A list or a table is one unit: its lines joined with semicolons.
    """
    if chunk.kind is not ChunkKind.TEXT:
        lines = [collapse(line.strip(" -•*")) for line in chunk.text.splitlines() if line.strip(" -•*")]
        joined = "; ".join(lines)
        return [joined[:MAX_CANDIDATE_CHARS]] if joined else []
    sentences: list[str] = []
    length = 0
    for sentence in usable_sentences(chunk.text):
        if sentences and length + len(sentence) + 1 > MAX_CANDIDATE_CHARS:
            break
        sentences.append(sentence)
        length += len(sentence) + 1
    return sentences


def candidate_block(
    candidates: Sequence[ScoredChunk], sources: Mapping[str, Source]
) -> tuple[str, dict[str, tuple[int, int]]]:
    """The numbered offer and, per sentence number, (index into ``candidates``, index of the sentence)."""
    lines: list[str] = []
    ids: dict[str, tuple[int, int]] = {}
    number = 0
    for index, item in enumerate(candidates):
        source = sources.get(item.chunk.source_id)
        sentences = numbered_sentences(item.chunk)
        if source is None or not sentences:
            continue
        number += 1
        lines.append(f"[{number}] ({source.title} › {item.chunk.full_heading}{_KIND_NOTE.get(item.chunk.kind, '')})")
        for position, sentence in enumerate(sentences):
            ids[f"{number}.{position + 1}"] = (index, position)
            lines.append(f"{number}.{position + 1} {sentence}")
    return "\n".join(lines), ids


def parse_selection(text: str) -> list[str] | None:
    """Sentence numbers from the JSON answer (its first list), ``None`` when the answer holds no such object."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    values = data.get("saetze")
    if not isinstance(values, list):
        values = next((value for value in data.values() if isinstance(value, list)), None)
        if values is None:
            return None
    return [item.strip().strip("[]").strip() for item in values if isinstance(item, str)]


class LlmSelector:
    def __init__(self, client: BApiClient) -> None:
        self.client = client

    def select(
        self,
        slot: TemplateSlot,
        candidates: Sequence[ScoredChunk],
        sources: Mapping[str, Source],
        *,
        topic: str,
        budget: RequestBudget,
        deadline: Deadline | None = None,
    ) -> Selection | LlmSkipped:
        """Choose the block's sentences among ``candidates``; ``LlmSkipped`` means: keep the rule-based choice."""
        passages, ids = candidate_block(candidates, sources)
        if not ids:
            return LlmSkipped("keine Kandidaten für den Baustein")
        prompt = get_prompt("passage_selection")
        messages = prompt.render(topic=topic, passages=passages, **slot_prompt_fields(slot))
        answer = budgeted_chat(
            self.client, messages, max_output_tokens=MAX_OUTPUT_TOKENS, budget=budget, what=slot.id, deadline=deadline
        )
        if isinstance(answer, LlmSkipped):
            return answer
        chosen = parse_selection(answer.text)
        if chosen is None:
            reason = f"unlesbare Antwort des Modells (finish_reason={answer.finish_reason or 'unbekannt'})"
            return LlmSkipped.after(reason, answer)
        unique = list(dict.fromkeys(chosen))
        picked = [ids[number] for number in unique if number in ids]
        excerpts, sentences, cut = _excerpts(candidates, picked, slot.budget.target_chars * LENGTH_FACTOR)
        return Selection(
            excerpts=excerpts,
            sentences=sentences,
            offered=len({index for index, _ in ids.values()}),
            invalid=len(unique) - len(picked),
            cut=cut,
            prompt=prompt.tag,
            model=answer.model,
            prompt_tokens=answer.prompt_tokens,
            completion_tokens=answer.completion_tokens,
            total_tokens=answer.total_tokens,
        )


def _excerpts(
    candidates: Sequence[ScoredChunk], picked: Sequence[tuple[int, int]], max_chars: float
) -> tuple[list[ScoredChunk], int, int]:
    """Excerpts in the order the model named their paragraphs, sentences in source order; stop past ``max_chars``."""
    by_paragraph: dict[int, set[int]] = {}
    for index, position in picked:
        by_paragraph.setdefault(index, set()).add(position)
    excerpts: list[ScoredChunk] = []
    sentences = cut = chars = 0
    for index, positions in by_paragraph.items():
        if excerpts and chars >= max_chars:
            cut += len(positions)
            continue
        item = candidates[index]
        chunk = item.chunk
        if chunk.kind is ChunkKind.TEXT:
            offered = numbered_sentences(chunk)
            chunk = chunk.model_copy(update={"text": " ".join(offered[p] for p in sorted(positions))})
        excerpts.append(
            ScoredChunk(chunk=chunk, score=item.score, matcher=MATCHER, reasons=[*item.reasons, "LLM-Auswahl"])
        )
        sentences += len(positions)
        chars += len(chunk.text)
    return excerpts, sentences, cut
