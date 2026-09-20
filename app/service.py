"""Orchestrator for part 1 (PLAN.md 3.1): resolve, corpus, segment, match, synthesise, assemble."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.compose.assembler import build_frontmatter, render_markdown
from app.compose.regeneration import PreservedSection, parse_document, to_keep
from app.domain.models import (
    AuditReport,
    Chunk,
    CollectionPart,
    Compendium,
    CurriculaPart,
    Resolution,
    ScoredChunk,
    SectionStatus,
    Source,
)
from app.domain.requests import GenerateRequest
from app.knowledge.segmentation import segment_source
from app.knowledge.topic import NormalizedTopic, normalize_topic, topic_stem
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.llm.gateway import LlmGateway
from app.llm.report import build_llm_report
from app.matching.fusion import smooth_sections
from app.matching.lexicon import HeadingLexicon
from app.matching.policy import AssignmentResult, assign
from app.matching.registry import STRATEGIES, UnknownMatcherError, ensure_strategy, get_matcher
from app.settings import Settings
from app.sources.lehrplan.part import CurriculaBuilder
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError
from app.sources.wlo.models import CollectionInfo
from app.sources.wlo.overview import PART_HEADING as COLLECTION_HEADING
from app.sources.wlo.part import CollectionBuilder, collection_topic
from app.sources.zim.registry import ZimRegistry
from app.synthesis.extraction import Extracted, ExtractionJob, ExtractionReport, extract_with_llm
from app.synthesis.facets import FacetCatalog
from app.synthesis.lint import lint_sections
from app.synthesis.writer import LlmJob, SectionWriter, WrittenSections
from app.templates.manager import TemplateManager
from app.templates.schema import Template, TemplateSlot

log = logging.getLogger(__name__)


class PartsUnavailableError(RuntimeError):
    """None of the requested parts can be generated with the configuration of this server."""


class TopicNotFoundError(LookupError):
    def __init__(self, resolution: Resolution) -> None:
        super().__init__(f"topic not found: {resolution.normalized}")
        self.resolution = resolution


@dataclass
class PreparedTopic:
    """Everything before matching: template, resolved topic, corpus and its chunks."""

    template: Template
    lexicon: HeadingLexicon
    normalized: NormalizedTopic
    resolution: Resolution
    sources: list[Source]
    chunks: list[Chunk]
    timings: dict[str, int] = field(default_factory=dict)
    subject: str | None = None
    collection: CollectionInfo | None = None
    knowledge: dict[str, Any] | None = None
    chunks_truncated: int = 0  # paragraphs the CORPUS_MAX_CHUNKS cap left out
    subtopics: list[str] = field(default_factory=list)  # part 2 keywords from the whole corpus, before the cap

    @property
    def sources_by_id(self) -> dict[str, Source]:
        return {s.source_id: s for s in self.sources}


@dataclass
class Matched:
    matcher: str
    assignment: AssignmentResult
    duration_ms: int


@dataclass
class WorldPart:
    """Part 1 of one request: what was written, how, and what the audit reports about it."""

    matcher: str | None  # None when part 1 was not requested: no strategy ran
    extraction: str  # the switches in effect: rule-based when the LLM cannot be used
    generation: str
    enrichment: str  # sources-only unless an LLM actually writes blocks and the request allowed more
    llm_note: str | None
    chunks_assigned: int = 0
    extracted: ExtractionReport | None = None  # extraction=llm: what the LLM chose, per block
    regenerated: list[str] = field(default_factory=list)  # content blocks made anew despite an earlier text
    written: WrittenSections = field(default_factory=lambda: WrittenSections(sections=[], citations=[]))


class _Stopwatch:
    """Writes the milliseconds since the previous lap into ``timings``."""

    def __init__(self, timings: dict[str, int]) -> None:
        self._timings = timings
        self._started = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self._timings[name] = int((now - self._started) * 1000)
        self._started = now


class CompendiumService:
    def __init__(
        self,
        registry: ZimRegistry,
        templates: TemplateManager,
        lexicon: HeadingLexicon,
        facets: FacetCatalog,
        settings: Settings,
        curricula: CurriculaBuilder | None = None,
        collections: CollectionBuilder | None = None,
        llm: LlmGateway | None = None,
    ) -> None:
        self.registry = registry
        self.templates = templates
        self.lexicon = lexicon
        self.facets = facets
        self.settings = settings
        self.curricula = curricula
        self.collections = collections
        self.llm = llm
        self.writer = SectionWriter(facets, settings.facets_level, registry.lookup)
        try:  # at start: a wrong default is the operator's error, not a 422 for every request
            ensure_strategy(settings.matcher_default)
        except UnknownMatcherError as exc:
            known = ", ".join(STRATEGIES)
            raise ValueError(f"MATCHER_DEFAULT={settings.matcher_default!r} is not a strategy ({known})") from exc

    def prepare(self, request: GenerateRequest, deadline: Deadline | None = None) -> PreparedTopic:
        """Resolve the topic, build the corpus and segment it: everything that precedes matching.

        Part 3 alone needs the collection only: its topic is resolved where possible, and no corpus is built.
        ``deadline`` bounds the repository reads of the knowledge collection; material texts not fetched in
        time are left out and counted in the audit.
        """
        timings: dict[str, int] = {}
        lap = _Stopwatch(timings).lap

        template = self.templates.get(request.template_id or self.settings.template_default)
        if request.empty_slot_policy:
            template = template.model_copy(update={"empty_slot_policy": request.empty_slot_policy})
        lexicon = self.lexicon.with_template(template)

        collection = self._collection_info(request)
        derived = collection_topic(collection) if collection is not None else None
        normalized = normalize_topic(request.topic or (derived.topic if derived else ""))
        context = [*normalized.context, *(derived.context if derived else [])]
        resolution = self.registry.resolve_topic(normalized.topic, context=context, query=normalized.query)
        # Part 1 and part 2 build on the corpus; part 3 alone, or with an unconfigured part 2, does not
        needs_corpus = "world" in request.parts or ("curricula" in request.parts and self.curricula is not None)
        if not resolution.resolved and needs_corpus:
            raise TopicNotFoundError(resolution)
        lap("resolve")
        prepared = PreparedTopic(
            template=template,
            lexicon=lexicon,
            normalized=normalized,
            resolution=resolution,
            sources=[],
            chunks=[],
            timings=timings,
            subject=request.subject or normalized.subject or (derived.subject if derived else None),
            collection=collection,
        )
        if needs_corpus:
            self._add_corpus(prepared, request, deadline)
        return prepared

    def _add_corpus(self, prepared: PreparedTopic, request: GenerateRequest, deadline: Deadline | None) -> None:
        """The articles of the topic, the sub-topics and, for part 1, the knowledge collection and the capped chunks."""
        lap = _Stopwatch(prepared.timings).lap
        sources = self.registry.build_corpus(
            prepared.resolution,
            slots=prepared.template.content_slots(),
            max_articles=request.max_articles or self.settings.corpus_max_articles,
        )
        lap("corpus")
        # The materials are sources of part 1 only; without it their texts would be read and thrown away
        if request.knowledge_collection_id and self.collections is not None and "world" in request.parts:
            prepared.knowledge = self._knowledge(request.knowledge_collection_id, sources, deadline)
            lap("knowledge")

        # The cap only decides which paragraphs part 1 uses; part 2 searches for every neighbour of the corpus.
        primary = next((s for s in sources if s.is_primary), sources[0] if sources else None)
        prepared.subtopics = _subtopics(sources, primary)
        if "world" not in request.parts:  # paragraphs and their cap serve part 1 only
            prepared.sources = sources
            return
        prepared.chunks, prepared.sources, prepared.chunks_truncated = _segment_corpus(
            sources, prepared.lexicon, self.settings.corpus_max_chunks
        )
        lap("segment")

    def _collection_info(self, request: GenerateRequest) -> CollectionInfo | None:
        """The collection behind the request; unreachable repositories only matter when the topic depends on it."""
        if not request.collection_id or self.collections is None:
            return None
        try:
            return self.collections.info(request.collection_id)
        except CollectionNotFoundError:
            raise
        except EduSharingError as exc:
            if request.topic:
                log.warning("collection %s not readable, continuing with the topic: %s", request.collection_id, exc)
                return None
            raise

    def _collections_or_fail(self) -> CollectionBuilder:
        if self.collections is None:
            raise RuntimeError("collections are not configured (EDU_SHARING_BASE_URL)")
        return self.collections

    def _knowledge(self, collection_id: str, sources: list[Source], deadline: Deadline | None) -> dict[str, Any]:
        """Add the reusable materials of the knowledge collection to the corpus; failures go to the audit."""
        try:
            expired = (lambda: deadline.remaining() <= 0) if deadline is not None else None
            result = self._collections_or_fail().knowledge_sources(collection_id, expired=expired)
        except EduSharingError as exc:
            log.warning("knowledge collection %s not readable: %s", collection_id, exc)
            return {"collection_id": collection_id, "error": str(exc), "sources": 0}
        sources.extend(result.sources)
        return {
            "collection_id": collection_id,
            "considered": result.considered,
            "sources": len(result.sources),
            "skipped_license": result.skipped_license,
            "empty": result.empty,
            "failed": result.failed,
            "timed_out": result.timed_out,
        }

    def _collection_part(self, collection_id: str, deadline: Deadline) -> CollectionPart:
        try:
            return self._collections_or_fail().overview(collection_id, expired=lambda: deadline.remaining() <= 0)
        except CollectionNotFoundError:
            raise
        except EduSharingError as exc:
            log.warning("collection %s overview failed: %s", collection_id, exc)
            markdown = f"{COLLECTION_HEADING}\n\n*Der Sammlungsüberblick ist nicht verfügbar: {exc}*\n"
            return CollectionPart(available=False, collection_id=collection_id, markdown=markdown, error=str(exc))

    def match(
        self,
        prepared: PreparedTopic,
        matcher_name: str | None,
        target_length: int,
    ) -> Matched:
        """Score and assign the prepared chunks with one matching strategy."""
        name = matcher_name or self.settings.matcher_default
        started = time.perf_counter()
        matcher = get_matcher(name, self.settings.model2vec_path)
        fused = matcher.score(prepared.template.slots, prepared.chunks)
        fused = smooth_sections(fused, prepared.chunks, self.settings.policy_section_smoothing)
        assignment = self._assign(prepared, fused, target_length)
        duration_ms = int((time.perf_counter() - started) * 1000)
        return Matched(matcher=name, assignment=assignment, duration_ms=duration_ms)

    def _assign(
        self,
        prepared: PreparedTopic,
        scores: dict[str, list[ScoredChunk]],
        target_length: int,
    ) -> AssignmentResult:
        return assign(
            _scale_budgets(prepared.template, target_length),
            prepared.chunks,
            scores,
            prepared.sources_by_id,
            confident_score=self.settings.policy_confident_score,
        )

    def generate(self, request: GenerateRequest) -> Compendium:
        deadline = Deadline(self.settings.request_timeout_s)  # bounds the LLM work; the rule-based path needs none
        if request.matcher:  # before any work; the configured default was checked at start
            ensure_strategy(request.matcher)
        unmakeable = self._unmakeable(request)
        if len(unmakeable) == len(set(request.parts)):  # an empty compendium would look like a success
            raise PartsUnavailableError("; ".join(unmakeable.values()))
        prepared = self.prepare(request, deadline)
        want_world = "world" in request.parts
        # The switches and the matcher describe how part 1 is made; parts 2 and 3 alone are rule-based by definition
        extraction_requested = request.extraction or self.settings.llm_extraction_default
        generation_requested = request.generation or self.settings.llm_generation_default
        enrichment_requested = request.enrichment or self.settings.llm_enrichment_default
        if not want_world:
            extraction_requested = generation_requested = "rule-based"
            enrichment_requested = "sources-only"
        timings = dict(prepared.timings)
        if want_world:
            switches = (extraction_requested, generation_requested, enrichment_requested)
            world = self._world_part(prepared, request, switches, deadline, timings)
        else:  # no matching, no synthesis, no LLM work
            world = WorldPart(
                matcher=None,
                extraction="rule-based",
                generation="rule-based",
                enrichment="sources-only",
                llm_note=None,
            )
        lap = _Stopwatch(timings).lap

        template, sources, chunks = prepared.template, prepared.sources, prepared.chunks
        normalized, resolution = prepared.normalized, prepared.resolution
        sections, citations, matcher_name = world.written.sections, world.written.citations, world.matcher
        facets_visible = self._facets_visible(request)
        topic = resolution.title or normalized.topic
        primary = next((s for s in sources if s.is_primary), sources[0] if sources else None)

        curricula: CurriculaPart | None = None
        if "curricula" in request.parts and self.curricula is not None:
            curricula = self.curricula.build(
                title=topic,
                aliases=list(primary.aliases) if primary else [],
                subtopics=prepared.subtopics,
                subject=prepared.subject,
                facets_visible=facets_visible,
            )
            lap("curricula")
        collection_part: CollectionPart | None = None
        if "collection" in request.parts and request.collection_id and self.collections is not None:
            collection_part = self._collection_part(request.collection_id, deadline)
            lap("collection")
        parts = ["world"] if want_world else []
        if curricula is not None:
            parts.append("curricula")
        if collection_part is not None:
            parts.append("collection")

        findings = lint_sections(template, sections, self.facets)
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        # The switches actually used: a switch without any LLM contribution is rule-based in the compendium.
        extracted, drafted = world.extracted, world.written.llm
        extraction_used = world.extraction if extracted and extracted.slots else "rule-based"
        generation_used = world.generation if drafted and drafted.sections else "rule-based"
        # Enrichment only means something where the LLM actually wrote a block
        enrichment_used = world.enrichment if generation_used != "rule-based" else "sources-only"
        llm_audit, llm_tokens, llm_front = build_llm_report(
            self.llm,
            extraction_requested=extraction_requested,
            extraction_used=extraction_used,
            generation_requested=generation_requested,
            generation_used=generation_used,
            enrichment_requested=enrichment_requested,
            enrichment_used=enrichment_used,
            note=world.llm_note,
            extraction=extracted,
            generation=drafted,
        )
        frontmatter = build_frontmatter(
            topic=topic,
            resolution={
                "query": resolution.query,
                "normalized": resolution.normalized,
                "context": resolution.context,
                "title": resolution.title,
                "path": resolution.path,
                "project": resolution.project,
                "alternatives": resolution.alternatives,
            },
            template=template,
            extraction=extraction_used,
            extraction_requested=extraction_requested,
            generation=generation_used,
            generation_requested=generation_requested,
            enrichment=enrichment_used,
            enriched_sentences=drafted.marked_sentences if drafted else 0,
            llm=llm_front,
            generated_at=generated_at,
            zim_snapshot=self.registry.snapshot(),
            matcher=matcher_name,
            parts=parts,
        )
        source_refs = [s.to_ref() for s in sources] if want_world else []  # the sources belong to part 1
        markdown = render_markdown(
            topic=topic,
            frontmatter=frontmatter,
            template=template,
            sections=sections,
            sources=source_refs,
            facets_visible=facets_visible,
            extra_parts=[part.markdown for part in (curricula, collection_part) if part is not None],
            include_world=want_world,
        )
        lap("assemble")

        filled = sum(1 for s in sections if s.status is not SectionStatus.EMPTY)
        parts_status = _parts_status(request, want_world, filled, curricula, collection_part)
        audit = AuditReport(
            matcher=matcher_name,
            timings_ms=timings,
            lint=findings,
            chunks_total=len(chunks),
            chunks_assigned=world.chunks_assigned,
            sections_filled=filled,
            sections_empty=len(sections) - filled,
            citations=len(citations),
            llm_tokens=llm_tokens,
            llm=llm_audit,
            knowledge=prepared.knowledge,
            chunks_truncated=prepared.chunks_truncated,
            parts_status=parts_status,
            regenerated=world.regenerated,
        )
        return Compendium(
            topic=topic,
            resolution=resolution,
            template_id=template.id,
            template_version=template.version,
            extraction=extraction_used,
            generation=generation_used,
            enrichment=enrichment_used,
            generated_at=generated_at,
            frontmatter=frontmatter,
            sections=sections,
            curricula=curricula,
            collection=collection_part,
            sources=source_refs,
            markdown=markdown,
            parts_status=parts_status,
            audit=audit,
        )

    def _unmakeable(self, request: GenerateRequest) -> dict[str, str]:
        """Requested parts this request cannot get from this server, with the reason."""
        reasons: dict[str, str] = {}
        if "curricula" in request.parts and self.curricula is None:
            reasons["curricula"] = "Teil 2 ist in diesem Dienst nicht eingerichtet"
        if "collection" in request.parts and self.collections is None:
            reasons["collection"] = "Teil 3 braucht ein edu-sharing-Repository (EDU_SHARING_BASE_URL)"
        elif "collection" in request.parts and not request.collection_id:
            reasons["collection"] = "Teil 3 braucht collection_id"
        return reasons

    def _facets_visible(self, request: GenerateRequest) -> bool:
        return self.settings.facets_visible if request.facets_visible is None else request.facets_visible

    def _world_part(
        self,
        prepared: PreparedTopic,
        request: GenerateRequest,
        requested: tuple[str, str, str],
        deadline: Deadline,
        timings: dict[str, int],
    ) -> WorldPart:
        """Part 1: match the chunks, let the LLM choose sentences and write blocks as the switches ask (D33).

        ``requested`` holds the extraction, the generation and the enrichment switch; without a usable LLM
        the first two run rule-based and nothing is enriched.
        """
        extraction_wanted, generation_wanted, enrichment_wanted = requested
        wants_llm = extraction_wanted != "rule-based" or generation_wanted != "rule-based"
        llm_note = self.llm_unavailable() if wants_llm else None
        extraction, generation = ("rule-based", "rule-based") if llm_note else (extraction_wanted, generation_wanted)
        enrichment = "sources-only" if generation == "rule-based" else enrichment_wanted
        llm = self.llm if wants_llm and llm_note is None else None
        budget = llm.open_budget() if llm is not None else None  # one budget for both switches
        matched = self.match(prepared, request.matcher, request.target_length)
        timings["match"] = matched.duration_ms
        lap = _Stopwatch(timings).lap

        # The scaled budgets carry ``target_length`` into the LLM prompts (target characters, output limit).
        template = _scale_budgets(prepared.template, request.target_length)
        topic = prepared.resolution.title or prepared.normalized.topic
        assigned: Mapping[str, Sequence[ScoredChunk]] = matched.assignment.assigned
        selected: set[str] = set()
        extracted: ExtractionReport | None = None
        if extraction == "llm" and budget is not None:
            result = self.extract(prepared, matched, request.target_length, budget=budget, deadline=deadline)
            if result is not None:
                assigned, selected, extracted = result.assigned, result.selected, result.report
            lap("extract")

        sources = prepared.sources
        primary = next((s for s in sources if s.is_primary), sources[0] if sources else None)
        llm_job: LlmJob | None = None
        if generation != "rule-based" and llm is not None and budget is not None:
            llm_job = LlmJob(
                synthesizer=llm.synthesizer,
                budget=budget,
                slots=llm.generation_slots(generation, (slot.id for slot in template.content_slots())),
                topic=topic,
                concurrency=llm.options.concurrency,
                deadline=deadline,
                enrich=enrichment == "model-knowledge",
            )
        preserved = self._preserved(request, template)
        written = self.writer.write(
            template,
            assigned,
            sources,
            prepared.sources_by_id,
            self._facets_visible(request),
            primary,
            prepared.lexicon,
            llm=llm_job,
            selected=selected,
            preserved=preserved,
        )
        lap("synthesize")
        return WorldPart(
            matcher=matched.matcher,
            extraction=extraction,
            generation=generation,
            enrichment=enrichment,
            llm_note=llm_note,
            chunks_assigned=sum(len(v) for v in assigned.values()),
            extracted=extracted,
            written=written,
            regenerated=(
                [slot.id for slot in template.content_slots() if slot.id not in preserved]
                if request.existing_markdown
                else []
            ),
        )

    def extract(
        self,
        prepared: PreparedTopic,
        matched: Matched,
        target_length: int,
        *,
        budget: RequestBudget | None = None,
        deadline: Deadline | None = None,
    ) -> Extracted | None:
        """extraction=llm on matched chunks (D33): the LLM's choice per block; ``None`` without a configured LLM.

        The caller checks ``llm_unavailable`` first; a budget of its own is opened when none is given (evaluation).
        """
        if self.llm is None:
            return None
        job = ExtractionJob(
            selector=self.llm.selector,
            budget=budget if budget is not None else self.llm.open_budget(),
            topic=prepared.resolution.title or prepared.normalized.topic,
            candidates=self.llm.options.extraction_candidates,
            concurrency=self.llm.options.concurrency,
            deadline=deadline,
        )
        template = _scale_budgets(prepared.template, target_length)  # the prompts name the target length
        return extract_with_llm(template, matched.assignment, prepared.chunks, prepared.sources_by_id, job)

    def _preserved(self, request: GenerateRequest, template: Template) -> dict[str, PreservedSection]:
        """Blocks of an earlier compendium that stay word for word (PLAN.md 4.6); generated blocks never do."""
        if not request.existing_markdown:
            return {}
        keep = to_keep(parse_document(request.existing_markdown), request.regenerate_sections)
        content = {slot.id for slot in template.content_slots()}
        return {slot_id: section for slot_id, section in keep.items() if slot_id in content}

    def llm_unavailable(self) -> str | None:
        """Why an LLM switch cannot be used now (D3, D10), or ``None``: it needs a configured, available LLM."""
        if self.llm is None:
            return "LLM nicht konfiguriert (LLM_ENABLED, B_API_KEY); Regelmodus verwendet"
        if not self.llm.available:
            return f"LLM nicht verfügbar ({self.llm.unavailable_reason}); Regelmodus verwendet"
        return None


def _parts_status(
    request: GenerateRequest,
    want_world: bool,
    filled: int,
    curricula: CurriculaPart | None,
    collection: CollectionPart | None,
) -> dict[str, str]:
    """What became of every requested part (PLAN.md 8.1): whole, empty, cut short or not available here."""
    status: dict[str, str] = {}
    if want_world:
        status["world"] = "ok" if filled else "empty"
    if "curricula" in request.parts:
        status["curricula"] = "unavailable" if curricula is None or not curricula.available else "ok"
    if "collection" in request.parts:
        if collection is None or not collection.available:
            status["collection"] = "unavailable"
        else:
            status["collection"] = "incomplete" if collection.summary.get("incomplete") else "ok"
    return status


# Which paragraphs survive CORPUS_MAX_CHUNKS: the topic's own articles, then the materials the request asked for,
# then the neighbours found by links and search. Anything else (lookups) comes last.
ORIGIN_PRIORITY = {"primary": 0, "same_topic": 1, "material": 2, "linked": 3, "search": 4}


def _segment_corpus(
    sources: list[Source], lexicon: HeadingLexicon, max_chunks: int
) -> tuple[list[Chunk], list[Source], int]:
    """Segment all sources and apply the chunk cap; return chunks, the sources that kept a chunk, and the cut count.

    Articles pulled in by search or by a link that does not carry the topic in its title contribute only paragraphs
    that mention the topic. The cap is filled in ``ORIGIN_PRIORITY`` order while chunks keep the corpus order; a
    source left without chunks is not listed (the primary article always is).
    """
    primary = next((s for s in sources if s.is_primary), None)
    stem = topic_stem(primary.title) if primary else ""
    segmented: list[list[Chunk]] = []
    for source in sources:
        source_chunks = segment_source(source, lexicon)
        needs_filter = source.origin in {"linked", "search"} and stem and stem not in source.title.lower()
        if needs_filter:
            source_chunks = [c for c in source_chunks if stem in f"{c.full_heading} {c.text}".lower()]
        segmented.append(source_chunks)

    allowed = [0] * len(sources)
    budget = max_chunks
    by_priority = sorted(
        range(len(sources)), key=lambda i: (ORIGIN_PRIORITY.get(sources[i].origin, len(ORIGIN_PRIORITY)), i)
    )
    for index in by_priority:
        allowed[index] = min(len(segmented[index]), budget)
        budget -= allowed[index]

    chunks: list[Chunk] = []
    kept: list[Source] = []
    for source, source_chunks, take in zip(sources, segmented, allowed, strict=True):
        if not take and not source.is_primary:
            continue
        kept.append(source)
        chunks.extend(source_chunks[:take])
    truncated = sum(len(source_chunks) for source_chunks in segmented) - len(chunks)
    if truncated:
        log.info("corpus capped at %d chunks; %d left out", max_chunks, truncated)
    return chunks, kept, truncated


def _subtopics(sources: list[Source], primary: Source | None) -> list[str]:
    """Titles of neighbouring articles that carry the topic stem: the sub-topics part 2 searches for."""
    if primary is None:
        return []
    stem = topic_stem(primary.title)
    if not stem:
        return []
    return [
        source.title
        for source in sources
        if not source.is_primary and source.origin in {"same_topic", "linked"} and stem in source.title.lower()
    ]


def _scale_budgets(template: Template, target_length: int) -> Template:
    """Distribute the requested total length over the content slots by weight."""
    content = template.content_slots()
    total_weight = sum(s.budget.weight for s in content) or 1.0
    scaled: list[TemplateSlot] = []
    for slot in template.slots:
        if slot.is_generated:
            scaled.append(slot)
            continue
        share = int(target_length * slot.budget.weight / total_weight)
        budget = slot.budget.model_copy(update={"target_chars": max(300, share)})
        scaled.append(slot.model_copy(update={"budget": budget}))
    return template.model_copy(update={"slots": scaled})
