"""LLM generation (PLAN.md 4.7, 7): the LLM writes a block from its evidence; only cited sentences survive.

The evidence block numbers the assigned chunks locally ([1] … [k]). After the call every sentence must carry
at least one valid marker; the rest is dropped and counted. Surviving markers are renumbered into the global
citation sequence of the compendium, so the sources table stays deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from app.domain.models import Chunk, Citation, ScoredChunk, Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.synthesis.citations import collapse, drop_unsupported, marker_numbers, renumber, verify_citations
from app.templates.schema import TemplateSlot

MAX_EVIDENCE_CHARS = 1500  # per chunk in the evidence block
MIN_OUTPUT_TOKENS = 200
MAX_OUTPUT_TOKENS = 1500
SNIPPET_CHARS = 220


@dataclass(frozen=True)
class LlmSection:
    text: str
    citations: list[Citation]
    prompt: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    dropped_sentences: int  # no valid citation marker
    unsupported_sentences: int = 0  # marker present, but the cited chunks do not cover the sentence
    marked_sentences: int = 0  # mark mode: failed sentences kept as conclusion blocks instead of being dropped


def evidence_block(
    scored: Sequence[ScoredChunk], sources: Mapping[str, Source]
) -> tuple[str, list[tuple[Chunk, Source]]]:
    """Numbered evidence lines ``[n] (source › heading) text`` and the chunks behind the numbers."""
    items: list[tuple[Chunk, Source]] = []
    lines: list[str] = []
    for item in scored:
        source = sources.get(item.chunk.source_id)
        if source is None:
            continue
        text = collapse(item.chunk.text)
        if len(text) > MAX_EVIDENCE_CHARS:
            text = text[: MAX_EVIDENCE_CHARS - 1].rstrip() + "…"
        items.append((item.chunk, source))
        lines.append(f"[{len(items)}] ({source.title} › {item.chunk.full_heading}) {text}")
    return "\n".join(lines), items


def slot_prompt_fields(slot: TemplateSlot) -> dict[str, object]:
    """The block's task as the LLM prompts show it: title, description, scope, sub-items and target length."""
    return {
        "title": slot.title,
        "description": slot.description or "–",
        "inclusions": slot.inclusions or "–",
        "exclusions": slot.exclusions or "–",
        "sub_items": "\n".join(f"- {item}" for item in slot.sub_items) or "–",
        "target_chars": slot.budget.target_chars,
    }


def shift_citations(section: LlmSection, offset: int) -> LlmSection:
    """Move a section written with local numbers into the global citation sequence (parallel drafts)."""
    if offset == 0:
        return section
    mapping = {c.number: c.number + offset for c in section.citations}
    citations = [c.model_copy(update={"number": c.number + offset}) for c in section.citations]
    return replace(section, text=renumber(section.text, mapping), citations=citations)


class LlmSynthesizer:
    def __init__(self, client: BApiClient, mark_unsupported: bool = False) -> None:
        self.client = client
        self.mark_unsupported = mark_unsupported  # LLM_UNSUPPORTED_SENTENCES=mark (PLAN.md 4.7)

    def write_section(
        self,
        slot: TemplateSlot,
        scored: Sequence[ScoredChunk],
        sources: Mapping[str, Source],
        *,
        topic: str,
        citation_start: int,
        budget: RequestBudget,
        deadline: Deadline | None = None,
    ) -> LlmSection | LlmSkipped:
        """Write one block from its assigned chunks; ``LlmSkipped`` means: use the extractive text."""
        evidence, items = evidence_block(scored, sources)
        if not items:
            return LlmSkipped("keine Belege für den Baustein")
        prompt = get_prompt("section_synthesis")
        messages = prompt.render(topic=topic, evidence=evidence, **slot_prompt_fields(slot))
        max_output = min(MAX_OUTPUT_TOKENS, max(MIN_OUTPUT_TOKENS, slot.budget.target_chars // 2))
        result = budgeted_chat(
            self.client, messages, max_output_tokens=max_output, budget=budget, what=slot.id, deadline=deadline
        )
        if isinstance(result, LlmSkipped):
            return result
        if not result.text.strip():
            # Measured: the model answers with nothing when the evidence does not fit the block.
            reason = f"leere Antwort des Modells (finish_reason={result.finish_reason or 'unbekannt'})"
            return LlmSkipped.after(reason, result)
        mark = self.mark_unsupported
        text, dropped = verify_citations(result.text, set(range(1, len(items) + 1)), mark=mark)
        evidence_texts = {n: chunk.text for n, (chunk, _) in enumerate(items, start=1)}
        text, unsupported = drop_unsupported(text, evidence_texts, mark=mark)
        if not marker_numbers(text):  # conclusion blocks alone are no evidence-based section
            reason = f"kein belegter Satz in der Antwort ({dropped} ohne Beleg, {unsupported} ohne Deckung im Beleg)"
            return LlmSkipped.after(reason, result)
        used = marker_numbers(text)
        mapping = {local: citation_start + index + 1 for index, local in enumerate(used)}
        citations = [
            Citation(
                number=mapping[local],
                source_id=source.source_id,
                chunk_id=chunk.chunk_id,
                source_title=source.title,
                source_url=source.url,
                section_heading=chunk.full_heading,
                snippet=collapse(chunk.text)[:SNIPPET_CHARS],
            )
            for local in used
            for chunk, source in (items[local - 1],)
        ]
        return LlmSection(
            text=renumber(text, mapping),
            citations=citations,
            prompt=prompt.tag,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            dropped_sentences=dropped,
            unsupported_sentences=unsupported,
            marked_sentences=dropped + unsupported if mark else 0,
        )
