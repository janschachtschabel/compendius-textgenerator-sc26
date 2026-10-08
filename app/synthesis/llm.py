"""LLM generation (PLAN.md 4.7, 7): the LLM writes a block from its evidence; only cited sentences survive.

The evidence block numbers the assigned chunks locally ([1] … [k]). After the call every sentence must carry
at least one valid marker; the rest is dropped and counted - or, where the request allows model knowledge, kept and
marked as such. Surviving markers are renumbered into the global citation sequence of the compendium, so the sources
table stays deterministic.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from app.domain.models import Chunk, Citation, ScoredChunk, Source
from app.knowledge.segmentation import split_sentences
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.synthesis.citations import (
    CONCLUSION,
    MODEL_KNOWLEDGE,
    collapse,
    drop_unsupported,
    escape_model_text,
    marker_numbers,
    opening_marker,
    renumber,
    verify_citations,
)
from app.synthesis.formulas import plain_formulas
from app.templates.schema import Template, TemplateSlot

MAX_EVIDENCE_CHARS = 1500  # per chunk in the evidence block
MIN_OUTPUT_TOKENS = 200
MAX_OUTPUT_TOKENS = 1500
# enrichment=model-knowledge-full (D69): the target length is a floor, so a block gets about one token per target
# character (some three characters of German each) up to this ceiling
MAX_FULL_OUTPUT_TOKENS = 4000
SNIPPET_CHARS = 220
NOT_TEXT = "Antwort ist kein Text (JSON)"
CUT_OFF = "Antwort am Ausgabelimit abgebrochen, kein Satz vollendet (finish_reason=length)"
# A finished sentence ends with its mark, maybe a closing quote or bracket, and the markers that cite it
_FINISHED_RE = re.compile(r"[.!?…][\"'»«“”)\]]*(?:\s*\[\d{1,3}\])*\s*$")


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
    marked_sentences: int = 0  # sentences kept marked instead of dropped (conclusions, or model knowledge)
    cut_off: bool = False  # the output limit cut the answer; the sentence it broke off in was struck


def is_json(text: str) -> bool:
    """An answer that is a JSON object or list, or begins as an object: no prose, whatever it holds."""
    stripped = text.strip()
    if stripped.startswith("{"):
        return True
    if not stripped.startswith("["):
        return False
    try:
        json.loads(stripped)
    except (ValueError, RecursionError):  # "[1] Das Thema …" is a text that opens with a marker
        return False
    return True


def without_unfinished_sentence(text: str) -> tuple[str, bool]:
    """``text`` without the sentence the output limit cut it off in, and whether there was one.

    Only the last line can be unfinished: a line break the model wrote ended the line before it, a list item too.
    In the last line the German sentence splitter finds where its last sentence starts (abbreviations and ordinals
    protected); a last line without a finished sentence goes whole.
    """
    head, newline, last = text.rstrip().rpartition("\n")
    sentences = split_sentences(last)
    if not sentences or _FINISHED_RE.search(sentences[-1]):
        return text, False
    # The splitter collapses blanks: the last sentence starts where its other characters are all behind
    start, remaining = len(last), sum(1 for char in sentences[-1] if not char.isspace())
    while remaining and start:
        start -= 1
        if not last[start].isspace():
            remaining -= 1
    return (head + newline + last[:start]).rstrip(), True


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


@dataclass(frozen=True)
class Coverage:
    """enrichment=model-knowledge-full (D69): what every block of a compendium is written against - the article the
    evidence comes from, and the overview of all blocks, which goes into the system message, the part the provider's
    prompt cache keeps."""

    article: str
    blocks: str


def blocks_overview(template: Template) -> str:
    """The content blocks of ``template`` with their tasks, alike for every topic and every target length."""
    lines = [
        f"- {slot.title}: {slot.description or '–'} Gehört hinein: {slot.inclusions or '–'} Gehört nicht hinein: "
        f"{slot.exclusions or '–'} Unterpunkte: {'; '.join(slot.sub_items) or '–'}"
        for slot in template.content_slots()
    ]
    return "Die Bausteine des Kompendiums:\n" + "\n".join(lines)


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
        enrich: bool = False,
        coverage: Coverage | None = None,
    ) -> LlmSection | LlmSkipped:
        """Write one block from its assigned chunks; ``LlmSkipped`` means: use the extractive text.

        With ``enrich`` the model may go beyond the evidence (enrichment=model-knowledge, docs/umbau.md U4):
        the other prompt asks for it, and an uncovered sentence is kept marked as Modellwissen instead of
        being dropped. A block without evidence, or whose answer cites none of it, is written from the model's
        knowledge, every sentence marked (Jan: "leere bausteine aus modellwissen", D72).

        With ``coverage`` (enrichment=model-knowledge-full, D69) the block is about ``topic`` as asked whatever the
        evidence holds: evidence where it meets the topic, model knowledge for the rest, marked sentence by
        sentence, and a block without evidence is written all the same. The target length is a floor, not a ceiling.
        """
        full = coverage is not None
        evidence, items = evidence_block(scored, sources)
        if not items and not (full or enrich):
            return LlmSkipped("keine Belege für den Baustein")
        if coverage is not None:
            prompt = get_prompt("section_coverage")
            messages = prompt.sharing(coverage.blocks).render(
                topic=topic,
                article=coverage.article or topic,
                title=slot.title,
                target_chars=slot.budget.target_chars,
                evidence=evidence or "(keine)",
            )
            max_output = min(MAX_FULL_OUTPUT_TOKENS, max(MIN_OUTPUT_TOKENS, slot.budget.target_chars))
        else:
            prompt = get_prompt("section_enrichment" if enrich else "section_synthesis")
            messages = prompt.render(topic=topic, evidence=evidence or "(keine)", **slot_prompt_fields(slot))
            max_output = min(MAX_OUTPUT_TOKENS, max(MIN_OUTPUT_TOKENS, slot.budget.target_chars // 2))
        result = budgeted_chat(
            self.client,
            messages,
            max_output_tokens=max_output,
            budget=budget,
            what=slot.id,
            deadline=deadline,
            prompt=prompt.id,
        )
        if isinstance(result, LlmSkipped):
            return result
        if not result.text.strip():
            # Measured: the model answers with nothing when the evidence does not fit the block.
            reason = f"leere Antwort des Modells (finish_reason={result.finish_reason or 'unbekannt'})"
            return LlmSkipped.after(reason, result)
        if is_json(result.text):  # a block is prose; kept, an object or a list stood in it as model knowledge
            return LlmSkipped.after(NOT_TEXT, result)
        answer, cut_off = result.text, False
        if result.finish_reason == "length":  # the output limit cut the answer, maybe inside a sentence
            answer, cut_off = without_unfinished_sentence(answer)
            if not answer.strip():
                return LlmSkipped.after(CUT_OFF, result)
        mark = MODEL_KNOWLEDGE if enrich or full else (CONCLUSION if self.mark_unsupported else "")
        # formulas the model wrote in LaTeX, as text: escaped for markdown every backslash showed (D83)
        text, dropped = verify_citations(plain_formulas(answer), set(range(1, len(items) + 1)), mark=mark)
        evidence_texts = {n: chunk.text for n, (chunk, _) in enumerate(items, start=1)}
        text, unsupported = drop_unsupported(text, evidence_texts, mark=mark)
        # conclusion blocks alone are no evidence-based section; marked model knowledge is a block wherever the request
        # allows it, with or without evidence to cite (D72; Jan, 2026-10-02: no verbatim block inside a written text)
        if not marker_numbers(text) and not ((full or enrich) and text.strip()):
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
            text=escape_model_text(renumber(text, mapping), mapping.values()),
            citations=citations,
            prompt=prompt.tag,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            dropped_sentences=dropped,
            unsupported_sentences=unsupported,
            marked_sentences=text.count(opening_marker(mark)) if mark else 0,  # what a reader sees marked
            cut_off=cut_off,
        )
