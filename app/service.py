"""Orchestrator for part 1 (PLAN.md 3.1): resolve, corpus, segment, match, synthesise, assemble."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.compose.assembler import build_frontmatter, render_markdown
from app.domain.models import (
    AuditReport,
    Chunk,
    CollectionPart,
    Compendium,
    CurriculaPart,
    Resolution,
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
from app.matching.policy import AssignmentResult, Doubt, assign
from app.matching.registry import ensure_strategy, get_matcher
from app.matching.router import RoutingResult
from app.settings import Settings
from app.sources.lehrplan.part import CurriculaBuilder
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError
from app.sources.wlo.models import CollectionInfo
from app.sources.wlo.overview import PART_HEADING as COLLECTION_HEADING
from app.sources.wlo.part import CollectionBuilder, collection_topic
from app.sources.zim.registry import ZimRegistry
from app.synthesis.facets import FacetCatalog
from app.synthesis.lint import lint_sections
from app.synthesis.writer import LlmJob, SectionWriter, WrittenSections
from app.templates.manager import TemplateManager
from app.templates.schema import Template, TemplateSlot

log = logging.getLogger(__name__)


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

    matcher: str
    mode: str
    llm_note: str | None
    chunks_assigned: int = 0
    routing: RoutingResult | None = None
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

    def prepare(self, request: GenerateRequest) -> PreparedTopic:
        """Resolve the topic, build the corpus and segment it: everything that precedes matching."""
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
        if not resolution.resolved:
            raise TopicNotFoundError(resolution)
        lap("resolve")

        sources = self.registry.build_corpus(
            resolution,
            slots=template.content_slots(),
            max_articles=request.max_articles or self.settings.corpus_max_articles,
        )
        lap("corpus")
        knowledge: dict[str, Any] | None = None
        if request.knowledge_collection_id and self.collections is not None:
            knowledge = self._knowledge(request.knowledge_collection_id, sources)
            lap("knowledge")

        chunks, sources = _segment_corpus(sources, lexicon, self.settings.corpus_max_chunks)
        lap("segment")
        return PreparedTopic(
            template=template,
            lexicon=lexicon,
            normalized=normalized,
            resolution=resolution,
            sources=sources,
            chunks=chunks,
            timings=timings,
            subject=request.subject or normalized.subject or (derived.subject if derived else None),
            collection=collection,
            knowledge=knowledge,
        )

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

    def _knowledge(self, collection_id: str, sources: list[Source]) -> dict[str, Any]:
        """Add the reusable materials of the knowledge collection to the corpus; failures go to the audit."""
        try:
            result = self._collections_or_fail().knowledge_sources(collection_id)
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
        }

    def _collection_part(self, collection_id: str) -> CollectionPart:
        try:
            return self._collections_or_fail().overview(collection_id)
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
        overrides: Mapping[str, str] | None = None,
    ) -> Matched:
        """Score and assign the prepared chunks with one matching strategy; ``overrides`` come from the LLM router."""
        name = matcher_name or self.settings.matcher_default
        started = time.perf_counter()
        matcher = get_matcher(name, self.settings.model2vec_path)
        fused = matcher.score(prepared.template.slots, prepared.chunks)
        fused = smooth_sections(fused, prepared.chunks, self.settings.policy_section_smoothing)
        assignment = assign(
            _scale_budgets(prepared.template, target_length),
            prepared.chunks,
            fused,
            prepared.sources_by_id,
            confident_score=self.settings.policy_confident_score,
            overrides=overrides,
        )
        return Matched(matcher=name, assignment=assignment, duration_ms=int((time.perf_counter() - started) * 1000))

    def generate(self, request: GenerateRequest) -> Compendium:
        deadline = Deadline(self.settings.request_timeout_s)  # bounds the LLM work; the rule-based path needs none
        matcher_default = ensure_strategy(request.matcher or self.settings.matcher_default)  # before any work
        prepared = self.prepare(request)
        mode_requested = request.mode or self.settings.llm_mode_default
        timings = dict(prepared.timings)
        want_world = "world" in request.parts
        if want_world:
            world = self._world_part(prepared, request, mode_requested, deadline, timings)
        else:  # parts 2 and 3 only: no matching, no synthesis, no LLM work
            world = WorldPart(matcher=matcher_default, mode="rule-based", llm_note=None)
        lap = _Stopwatch(timings).lap

        template, sources, chunks = prepared.template, prepared.sources, prepared.chunks
        normalized, resolution = prepared.normalized, prepared.resolution
        sections, citations, routing = world.written.sections, world.written.citations, world.routing
        matcher_name, mode, llm_note = world.matcher, world.mode, world.llm_note
        facets_visible = self._facets_visible(request)
        topic = resolution.title or normalized.topic
        primary = next((s for s in sources if s.is_primary), sources[0] if sources else None)

        curricula: CurriculaPart | None = None
        if "curricula" in request.parts and self.curricula is not None:
            curricula = self.curricula.build(
                title=topic,
                aliases=list(primary.aliases) if primary else [],
                subtopics=_subtopics(sources, primary),
                subject=prepared.subject,
                facets_visible=facets_visible,
            )
            lap("curricula")
        collection_part: CollectionPart | None = None
        if "collection" in request.parts and request.collection_id and self.collections is not None:
            collection_part = self._collection_part(request.collection_id)
            lap("collection")
        parts = ["world"] if want_world else []
        if curricula is not None:
            parts.append("curricula")
        if collection_part is not None:
            parts.append("collection")

        findings = lint_sections(template, sections, self.facets)
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        # The mode actually used: a hybrid request without any LLM contribution is a rule-based compendium.
        llm_report = world.written.llm
        llm_contributed = bool(llm_report and llm_report.sections) or bool(routing and routing.moved)
        mode_used = mode if llm_contributed else "rule-based"
        llm_audit, llm_tokens, llm_front = build_llm_report(
            self.llm, mode_requested, mode_used, llm_note, llm_report, routing
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
            mode=mode_used,
            mode_requested=mode_requested,
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
        )
        return Compendium(
            topic=topic,
            resolution=resolution,
            template_id=template.id,
            template_version=template.version,
            mode=mode_used,
            generated_at=generated_at,
            frontmatter=frontmatter,
            sections=sections,
            curricula=curricula,
            collection=collection_part,
            sources=source_refs,
            markdown=markdown,
            audit=audit,
        )

    def _facets_visible(self, request: GenerateRequest) -> bool:
        return self.settings.facets_visible if request.facets_visible is None else request.facets_visible

    def _world_part(
        self,
        prepared: PreparedTopic,
        request: GenerateRequest,
        mode_requested: str,
        deadline: Deadline,
        timings: dict[str, int],
    ) -> WorldPart:
        """Part 1: match the chunks, let the LLM settle close calls (hybrid modes) and write the sections."""
        mode, llm_note = self._resolve_mode(mode_requested)
        budget = self.llm.open_budget() if mode != "rule-based" and self.llm is not None else None
        matched = self.match(prepared, request.matcher, request.target_length)
        timings["match"] = matched.duration_ms
        lap = _Stopwatch(timings).lap

        routing = self._route(prepared, matched.assignment.doubtful, budget, deadline)
        if routing is not None:
            if routing.overrides:
                matched = self.match(prepared, request.matcher, request.target_length, overrides=routing.overrides)
            lap("route")

        template, sources = prepared.template, prepared.sources
        primary = next((s for s in sources if s.is_primary), sources[0] if sources else None)
        llm_job: LlmJob | None = None
        if budget is not None and self.llm is not None:
            llm_job = LlmJob(
                synthesizer=self.llm.synthesizer,
                budget=budget,
                slots=self.llm.llm_slots(mode, (slot.id for slot in template.content_slots())),
                topic=prepared.resolution.title or prepared.normalized.topic,
                concurrency=self.llm.options.concurrency,
                deadline=deadline,
            )
        # The scaled budgets carry ``target_length`` into the LLM prompts (target characters, output limit).
        written = self.writer.write(
            _scale_budgets(template, request.target_length),
            matched.assignment.assigned,
            sources,
            prepared.sources_by_id,
            self._facets_visible(request),
            primary,
            prepared.lexicon,
            llm=llm_job,
        )
        lap("synthesize")
        return WorldPart(
            matcher=matched.matcher,
            mode=mode,
            llm_note=llm_note,
            chunks_assigned=sum(len(v) for v in matched.assignment.assigned.values()),
            routing=routing,
            written=written,
        )

    def _resolve_mode(self, requested: str) -> tuple[str, str | None]:
        """The mode the request can run in: hybrid modes need a configured and available LLM (D3, D10)."""
        if requested == "rule-based":
            return requested, None
        if self.llm is None:
            return "rule-based", "LLM nicht konfiguriert (LLM_ENABLED, B_API_KEY); Regelmodus verwendet"
        if not self.llm.available:
            return "rule-based", f"LLM nicht verfügbar ({self.llm.unavailable_reason}); Regelmodus verwendet"
        return requested, None

    def _route(
        self, prepared: PreparedTopic, doubts: list[Doubt], budget: RequestBudget | None, deadline: Deadline
    ) -> RoutingResult | None:
        """Let the LLM decide the close calls of the policy (hybrid modes with an enabled router)."""
        if budget is None or self.llm is None or self.llm.router is None or not doubts:
            return None
        chunks = {chunk.chunk_id: chunk for chunk in prepared.chunks}
        try:
            return self.llm.router.route(doubts, chunks, prepared.template, budget, deadline=deadline)
        except Exception as exc:
            # Same rule as for the drafts: a failing router leaves the policy decision as it is.
            log.exception("LLM router failed unexpectedly")
            return RoutingResult(considered=len(doubts), skipped=f"unerwarteter Fehler ({type(exc).__name__})")


def _segment_corpus(
    sources: list[Source], lexicon: HeadingLexicon, max_chunks: int
) -> tuple[list[Chunk], list[Source]]:
    """Segment all sources; articles pulled in by search or by a link that does not carry the
    topic in its title contribute only paragraphs that mention the topic, otherwise they are dropped."""
    primary = next((s for s in sources if s.is_primary), None)
    stem = topic_stem(primary.title) if primary else ""
    chunks: list[Chunk] = []
    kept: list[Source] = []
    for source in sources:
        source_chunks = segment_source(source, lexicon)
        needs_filter = source.origin in {"linked", "search"} and stem and stem not in source.title.lower()
        if needs_filter:
            source_chunks = [c for c in source_chunks if stem in f"{c.full_heading} {c.text}".lower()]
        if not source_chunks and not source.is_primary:
            continue
        kept.append(source)
        chunks.extend(source_chunks)
    return chunks[:max_chunks], kept


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
