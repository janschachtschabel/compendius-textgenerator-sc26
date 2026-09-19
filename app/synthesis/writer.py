"""Writes the part 1 sections of a compendium: text per content slot, generated blocks after them.

Extracted from the orchestrator (``service.py``). In the hybrid modes (PLAN.md 4.7) an ``LlmJob`` names the
slots the LLM writes; their drafts are produced in parallel with local citation numbers and shifted into the
global sequence while the sections are assembled in template order. Every slot the LLM cannot deliver falls
back to the extractive text and is listed in the ``LlmReport``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.domain.models import Citation, ScoredChunk, Section, SectionStatus, Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped
from app.llm.deadline import Deadline
from app.matching.lexicon import HeadingLexicon
from app.synthesis import facets as facet_rules
from app.synthesis.actors import build_actors_section, collect_actors
from app.synthesis.extractive import synthesize
from app.synthesis.facets import FacetCatalog
from app.synthesis.glossary import build_glossary
from app.synthesis.llm import LlmSection, LlmSynthesizer, shift_citations
from app.synthesis.sources_section import build_sources_section
from app.templates.schema import Template, TemplateSlot

log = logging.getLogger(__name__)

ACTOR_SLOT_KEY = "akteure"

Lookup = Callable[[str], Source | None]


@dataclass
class LlmJob:
    """What the hybrid modes hand to the writer: the synthesizer, the request budget and the slots to write."""

    synthesizer: LlmSynthesizer
    budget: RequestBudget
    slots: set[str]
    topic: str
    concurrency: int = 4
    deadline: Deadline | None = None


@dataclass
class LlmReport:
    sections: list[str] = field(default_factory=list)  # slot ids the LLM wrote
    fallbacks: dict[str, str] = field(default_factory=dict)  # slot id -> why the extractive text was used
    prompts: set[str] = field(default_factory=set)
    model: str | None = None
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    dropped_sentences: int = 0
    unsupported_sentences: int = 0
    marked_sentences: int = 0


@dataclass
class WrittenSections:
    sections: list[Section]
    citations: list[Citation]
    llm: LlmReport | None = None


class SectionWriter:
    def __init__(self, facets: FacetCatalog, facets_level: str, lookup: Lookup) -> None:
        self.facets = facets
        self.facets_level = facets_level
        self.lookup = lookup

    def write(
        self,
        template: Template,
        assigned: Mapping[str, Sequence[ScoredChunk]],
        sources: Sequence[Source],
        sources_by_id: Mapping[str, Source],
        facets_visible: bool,
        primary: Source | None,
        lexicon: HeadingLexicon,
        llm: LlmJob | None = None,
    ) -> WrittenSections:
        drafts = _draft_with_llm(template, assigned, sources_by_id, llm) if llm is not None else {}
        report = LlmReport() if llm is not None else None
        sections: list[Section] = []
        all_citations: list[Citation] = []
        seen_sentences: set[str] = set()
        for slot in template.slots:
            if slot.is_generated:
                sections.append(Section(slot_id=slot.id, slot_key=slot.slot, title=slot.title))
                continue
            scored = assigned.get(slot.id, [])
            chunks = [sc.chunk for sc in scored]
            section = Section(
                slot_id=slot.id,
                slot_key=slot.slot,
                title=slot.title,
                chunk_ids=[c.chunk_id for c in chunks],
                matching={
                    "candidates": [
                        {"chunk_id": sc.chunk.chunk_id, "score": sc.score, "reasons": sc.reasons} for sc in scored
                    ]
                },
            )
            draft = drafts.get(slot.id)
            if isinstance(draft, LlmSection) and report is not None:
                draft = shift_citations(draft, len(all_citations))
                section.text, section.citations, section.status = draft.text, draft.citations, SectionStatus.LLM
                section.llm = {
                    "prompt": draft.prompt,
                    "model": draft.model,
                    "tokens": draft.total_tokens,
                    "dropped_sentences": draft.dropped_sentences,
                    "unsupported_sentences": draft.unsupported_sentences,
                    "marked_sentences": draft.marked_sentences,
                }
                cited = {c.chunk_id for c in draft.citations}
                chunks = [c for c in chunks if c.chunk_id in cited] or chunks
                _account(report, slot.id, draft)
            else:
                if isinstance(draft, LlmSkipped) and report is not None:
                    report.fallbacks[slot.id] = draft.reason
                    _account_skipped(report, draft)
                text, citations = synthesize(scored, sources_by_id, len(all_citations), seen_sentences)
                section.text, section.citations = text, citations
                section.status = SectionStatus.EXTRACTIVE if text else SectionStatus.EMPTY
            all_citations.extend(section.citations)
            if section.text:
                section.facets = facet_rules.annotate(slot, chunks, sources_by_id, self.facets, self.facets_level)
                if isinstance(draft, LlmSection) and draft.marked_sentences and "Evidenzgrad" in section.facets:
                    section.facets["Evidenzgrad"] = [*section.facets["Evidenzgrad"], "Schlussfolgerung"]
            sections.append(section)

        for section in sections:
            gen_slot = _slot(template, section.slot_id)
            if gen_slot is None or not gen_slot.is_generated:
                continue
            text, facets = self._generate(gen_slot, primary, sources, all_citations, facets_visible, lexicon)
            section.text = text
            section.facets = facets if text else {}
            section.status = SectionStatus.GENERATED if text else SectionStatus.EMPTY
        return WrittenSections(sections=sections, citations=all_citations, llm=report)

    def _generate(
        self,
        slot: TemplateSlot,
        primary: Source | None,
        sources: Sequence[Source],
        citations: Sequence[Citation],
        facets_visible: bool,
        lexicon: HeadingLexicon,
    ) -> tuple[str, dict[str, list[str]]]:
        if slot.generator == "sources":
            return build_sources_section(sources, citations, facets_visible), {
                "Zugang": ["frei"],
                "Vertrauensgrad": ["hoch"],
            }
        if slot.generator == "glossary":
            topic = primary.title if primary else ""
            aliases = primary.aliases if primary else []
            return build_glossary(topic, primary, sources, aliases), {}
        if slot.generator == "actors":
            preferred = set()
            if primary is not None:
                preferred = {s.heading for s in primary.sections if lexicon.classify(s.path) == ACTOR_SLOT_KEY}
            actors = collect_actors(primary, sources, self.lookup, preferred_headings=preferred)
            functions = list(dict.fromkeys(f for a in actors for f in a.functions))
            facets = {"Akteursfunktion": functions} if functions else {}
            return build_actors_section(actors, facets_visible), facets
        return "", {}


def _draft_with_llm(
    template: Template,
    assigned: Mapping[str, Sequence[ScoredChunk]],
    sources_by_id: Mapping[str, Source],
    job: LlmJob,
) -> dict[str, LlmSection | LlmSkipped]:
    """Drafts for every LLM slot with assigned chunks, in parallel, numbered locally from 1."""
    slots = [slot for slot in template.content_slots() if slot.id in job.slots and assigned.get(slot.id)]
    if not slots:
        return {}

    def draft(slot: TemplateSlot) -> LlmSection | LlmSkipped:
        try:
            return job.synthesizer.write_section(
                slot,
                assigned[slot.id],
                sources_by_id,
                topic=job.topic,
                citation_start=0,
                budget=job.budget,
                deadline=job.deadline,
            )
        except Exception as exc:
            # The LLM layer must never break the rule-based path (PLAN.md 4.7): log it, write the block extractively.
            log.exception("LLM draft for %s failed unexpectedly", slot.id)
            return LlmSkipped(f"unerwarteter Fehler ({type(exc).__name__})")

    with ThreadPoolExecutor(max_workers=max(1, min(job.concurrency, len(slots)))) as pool:
        results = list(pool.map(draft, slots))
    return {slot.id: result for slot, result in zip(slots, results, strict=True)}


def _account(report: LlmReport, slot_id: str, draft: LlmSection) -> None:
    report.sections.append(slot_id)
    report.prompts.add(draft.prompt)
    report.model = draft.model
    report.calls += 1
    report.prompt_tokens += draft.prompt_tokens
    report.completion_tokens += draft.completion_tokens
    report.total_tokens += draft.total_tokens
    report.dropped_sentences += draft.dropped_sentences
    report.unsupported_sentences += draft.unsupported_sentences
    report.marked_sentences += draft.marked_sentences


def _account_skipped(report: LlmReport, skipped: LlmSkipped) -> None:
    report.calls += skipped.calls
    report.prompt_tokens += skipped.prompt_tokens
    report.completion_tokens += skipped.completion_tokens
    report.total_tokens += skipped.total_tokens


def _slot(template: Template, slot_id: str) -> TemplateSlot | None:
    return next((s for s in template.slots if s.id == slot_id), None)
