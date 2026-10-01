"""Writes the part 1 sections of a compendium: text per content slot, generated blocks after them.

Extracted from the orchestrator (``service.py``). With LLM generation (PLAN.md 4.7) an ``LlmJob`` names the
slots the LLM writes; their drafts are produced in parallel with local citation numbers and shifted into the
global sequence while the sections are assembled in template order. Blocks in ``preserved`` come from an
earlier compendium (PLAN.md 4.6): they are copied word for word with their citation numbers, and the new
blocks are numbered after the highest of them. Every slot the LLM cannot deliver falls
back to the extractive text and is listed in the ``LlmReport``. Slots in ``selected`` hold excerpts whose
sentences the LLM chose (extraction=llm, D33); their extractive text keeps all of those sentences. Slots in
``ai_assigned`` hold paragraphs an LLM assigned (matcher=llm, D34); like ``selected`` they are marked as chosen by
an AI, but keep the first sentences of each paragraph.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field

from app.compose.regeneration import PreservedSection
from app.concurrency import map_in_threads
from app.domain.models import Citation, ScoredChunk, Section, SectionStatus, Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, skipped_on_error
from app.llm.deadline import Deadline
from app.llm.usage import Tokens
from app.matching.lexicon import HeadingLexicon
from app.synthesis import facets as facet_rules
from app.synthesis.actors import build_actors_section, collect_actors
from app.synthesis.citations import CONCLUSION, MODEL_KNOWLEDGE, marker_numbers
from app.synthesis.extractive import synthesize
from app.synthesis.facets import FacetCatalog
from app.synthesis.glossary import build_glossary
from app.synthesis.llm import Coverage, LlmSection, LlmSynthesizer, blocks_overview, shift_citations
from app.synthesis.safe_markdown import defuse, no_definitions
from app.synthesis.sources_section import build_sources_section
from app.templates.schema import ACTORS_KEY, Template, TemplateSlot

Lookup = Callable[[str], Source | None]


@dataclass
class LlmJob:
    """What LLM generation hands to the writer: the synthesizer, the request budget and the slots to write."""

    synthesizer: LlmSynthesizer
    budget: RequestBudget
    slots: set[str]
    topic: str
    concurrency: int = 10  # the service passes LlmOptions.concurrency; this is only the bare default
    deadline: Deadline | None = None
    enrich: bool = False  # enrichment=model-knowledge: the model may add its own knowledge (docs/umbau.md U4)
    # enrichment=model-knowledge-full (D69): every slot is written, also one without chunks; ``article`` names the
    # article the evidence comes from when ``topic`` is the topic as asked
    full: bool = False
    article: str = ""


@dataclass
class LlmReport(Tokens):
    sections: list[str] = field(default_factory=list)  # slot ids the LLM wrote
    fallbacks: dict[str, str] = field(default_factory=dict)  # slot id -> why the extractive text was used
    prompts: set[str] = field(default_factory=set)
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
        selected: Collection[str] = frozenset(),
        ai_assigned: Collection[str] = frozenset(),
        preserved: Mapping[str, PreservedSection] | None = None,
        carried: Sequence[Source] = (),
        lookup: Lookup | None = None,
    ) -> WrittenSections:
        kept = dict(preserved or {})
        drafts = _draft_with_llm(template, assigned, sources_by_id, llm, skip=set(kept)) if llm is not None else {}
        report = LlmReport() if llm is not None else None
        sections: list[Section] = []
        all_citations: list[Citation] = [c for block in kept.values() for c in block.citations]
        # The new blocks count on from the highest number a kept block cites, read from its markers: a row the
        # parser cannot read would otherwise lower it, and a new block would take a number the kept one still
        # uses (audit 2026-09-27, KO-02)
        highest = max((number for block in kept.values() for number in marker_numbers(block.text)), default=0)
        seen_sentences: set[str] = set()
        for slot in template.slots:
            block = kept.get(slot.id)
            if block is not None and not slot.is_generated:
                sections.append(_preserved_section(slot, block))
                continue
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
                draft = shift_citations(draft, highest)
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
                chosen = slot.id in selected
                text, citations = synthesize(scored, sources_by_id, highest, seen_sentences, all_sentences=chosen)
                section.text, section.citations = text, citations
                if not text:
                    section.status = SectionStatus.EMPTY
                else:
                    by_ai = chosen or slot.id in ai_assigned
                    section.status = SectionStatus.LLM_SELECTED if by_ai else SectionStatus.EXTRACTIVE
            all_citations.extend(section.citations)
            highest = max(highest, *(c.number for c in section.citations)) if section.citations else highest
            if section.text:
                section.facets = facet_rules.annotate(slot, chunks, sources_by_id, self.facets, self.facets_level)
                if isinstance(draft, LlmSection) and draft.marked_sentences and "Evidenzgrad" in section.facets:
                    grade = MODEL_KNOWLEDGE if llm is not None and llm.enrich else CONCLUSION
                    section.facets["Evidenzgrad"] = [*section.facets["Evidenzgrad"], grade]
            sections.append(section)

        all_citations.sort(key=lambda citation: citation.number)  # kept and new blocks in one sequence
        for section in sections:
            gen_slot = _slot(template, section.slot_id)
            if gen_slot is None or not gen_slot.is_generated:
                continue
            text, facets = self._generate(
                gen_slot, primary, sources, all_citations, facets_visible, lexicon, carried=carried, lookup=lookup
            )
            section.text = text
            section.facets = facets if text else {}
            section.status = SectionStatus.GENERATED if text else SectionStatus.EMPTY
        # The net behind every writer of part 1 (audit 2026-09-28, SE-16), kept blocks included: an earlier compendium
        # may come from a CMS other people edit, and a tag or a link it held reached the reader as sent. What the
        # service wrote itself passes the net unchanged, so a reviewed block stays word for word (audit 2026-09-29,
        # T6)
        for section in sections:
            section.text = defuse(section.text)
            if section.slot_id in kept and not _is_generated(template, section.slot_id):
                section.text = no_definitions(section.text)
        return WrittenSections(sections=sections, citations=all_citations, llm=report)

    def _generate(
        self,
        slot: TemplateSlot,
        primary: Source | None,
        sources: Sequence[Source],
        citations: Sequence[Citation],
        facets_visible: bool,
        lexicon: HeadingLexicon,
        carried: Sequence[Source] = (),
        lookup: Lookup | None = None,
    ) -> tuple[str, dict[str, list[str]]]:
        if slot.generator == "sources":
            # the sources only kept blocks cite keep their entry, authors and licence (audit 2026-09-29, A04)
            return build_sources_section([*sources, *carried], citations, facets_visible), {
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
                persons = {ACTORS_KEY, slot.slot}  # the shared lexicon's key and the template's own (AR-04)
                preferred = {s.heading for s in primary.sections if lexicon.classify(s.path) in persons}
            actors = collect_actors(primary, sources, lookup or self.lookup, preferred_headings=preferred)
            functions = list(dict.fromkeys(f for a in actors for f in a.functions))
            facets = {"Akteursfunktion": functions} if functions else {}
            return build_actors_section(actors, facets_visible), facets
        return "", {}


def _preserved_section(slot: TemplateSlot, block: PreservedSection) -> Section:
    """A block of the earlier compendium, word for word, with the status and facets it had."""
    return Section(
        slot_id=slot.id,
        slot_key=slot.slot,
        title=slot.title,
        text=block.text,
        citations=list(block.citations),
        facets=dict(block.facets),
        status=block.status,
    )


def _draft_with_llm(
    template: Template,
    assigned: Mapping[str, Sequence[ScoredChunk]],
    sources_by_id: Mapping[str, Source],
    job: LlmJob,
    skip: set[str],
) -> dict[str, LlmSection | LlmSkipped]:
    """Drafts for every LLM slot with assigned chunks (in full mode for every LLM slot), in parallel, numbered
    locally from 1."""
    slots = [
        slot
        for slot in template.content_slots()
        if slot.id in job.slots and (job.full or assigned.get(slot.id)) and slot.id not in skip
    ]
    if not slots:
        return {}
    coverage = Coverage(article=job.article, blocks=blocks_overview(template)) if job.full else None

    def draft(slot: TemplateSlot) -> LlmSection | LlmSkipped:
        return job.synthesizer.write_section(
            slot,
            assigned.get(slot.id, []),
            sources_by_id,
            topic=job.topic,
            citation_start=0,
            budget=job.budget,
            deadline=job.deadline,
            enrich=job.enrich,
            coverage=coverage,
        )

    # An unexpected error writes that block extractively
    results = map_in_threads(skipped_on_error(draft, lambda slot: f"LLM draft for {slot.id}"), slots, job.concurrency)
    return {slot.id: result for slot, result in zip(slots, results, strict=True)}


def _account(report: LlmReport, slot_id: str, draft: LlmSection) -> None:
    report.sections.append(slot_id)
    report.prompts.add(draft.prompt)
    report.model = draft.model
    report.add(draft)
    report.dropped_sentences += draft.dropped_sentences
    report.unsupported_sentences += draft.unsupported_sentences
    report.marked_sentences += draft.marked_sentences


def _account_skipped(report: LlmReport, skipped: LlmSkipped) -> None:
    report.add(skipped, skipped.calls)


def _is_generated(template: Template, slot_id: str) -> bool:
    slot = _slot(template, slot_id)
    return slot is not None and slot.is_generated


def _slot(template: Template, slot_id: str) -> TemplateSlot | None:
    return next((s for s in template.slots if s.id == slot_id), None)
