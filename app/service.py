"""Orchestrator for part 1 (PLAN.md 3.1): resolve, corpus, segment, match, synthesise, assemble."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.compose.assembler import build_frontmatter, render_markdown
from app.compose.regeneration import PreservedSection, parse_document, to_keep
from app.domain.models import (
    AuditReport,
    Chunk,
    CollectionPart,
    Compendium,
    CurriculaPart,
    NodeInput,
    Resolution,
    ScoredChunk,
    SectionStatus,
    Source,
)
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import (
    CHECKED_ORIGINS,
    ArticleChoiceJob,
    ArticleChoiceReport,
    HitCheckReport,
    check_hits,
    choice_used,
)
from app.knowledge.main_article import choose_main_article
from app.knowledge.node_article import NodeArticleReport, node_block
from app.knowledge.segmentation import segment_source
from app.knowledge.topic import NormalizedTopic, topic_stem
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.llm.gateway import LlmGateway
from app.llm.report import build_llm_report
from app.matching.fusion import smooth_sections
from app.matching.lexicon import HeadingLexicon
from app.matching.llm_assignment import MATCHER as LLM_ASSIGNED
from app.matching.llm_assignment import AssignmentJob, LlmAssignmentReport, assign_with_llm
from app.matching.policy import AssignmentResult, assign
from app.matching.registry import LLM_MATCHER, STRATEGIES, UnknownMatcherError, ensure_strategy, get_matcher
from app.settings import Settings
from app.sources.lehrplan.part import CurriculaBuilder
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.wlo.client import CollectionNotFoundError, EduSharingClient, EduSharingError
from app.sources.wlo.models import CollectionInfo, NodeInfo
from app.sources.wlo.overview import PART_HEADING as COLLECTION_HEADING
from app.sources.wlo.part import (
    CollectionBuilder,
    CollectionOptions,
    CollectionTopic,
    collection_topic,
    node_input,
    node_topic,
)
from app.sources.wlo.repository import repository_root
from app.sources.zim.registry import CHOSEN_BY_LLM, NODE_ORIGIN, ZimRegistry
from app.synthesis.extraction import Extracted, ExtractionJob, ExtractionReport, extract_with_llm
from app.synthesis.facets import FacetCatalog
from app.synthesis.lint import lint_sections
from app.synthesis.writer import LlmJob, SectionWriter, WrittenSections
from app.templates.manager import TemplateManager
from app.templates.schema import Template, TemplateSlot

log = logging.getLogger(__name__)


class PartsUnavailableError(RuntimeError):
    """None of the requested parts can be generated with the configuration of this server."""


class RepositoryUnavailableError(RuntimeError):
    """No repository to read a node or a collection from: none is configured and the request names none."""


NO_REPOSITORY = "Kein Repository konfiguriert (EDU_SHARING_BASE_URL)"


NOT_FOUND = "Thema in den Archiven nicht gefunden"
NO_SUBJECT_TOPIC = "Das LLM sieht in diesem Material kein fachliches Thema; topic angeben"
NO_MATERIAL_ARTICLE = (
    "Zu diesem Material fanden die Regeln keinen Artikel: weder sein Titel noch die Begriffe aus Titel und "
    "Beschreibung führen zu einem; topic angeben, oder article_choice llm lässt das LLM das Thema bestimmen"
)
NO_ARTICLE_AFTER_LLM = "Zu diesem Material fanden weder das LLM noch die Regeln einen Artikel; topic angeben"


class TopicNotFoundError(LookupError):
    """No article for the request; ``node`` says how the article of a material was sought (D47).

    ``from_material``: the material alone was to name the article (no topic came along), so the message says why that
    failed and what to send instead.
    """

    def __init__(
        self, resolution: Resolution, node: NodeArticleReport | None = None, *, from_material: bool = False
    ) -> None:
        super().__init__(f"topic not found: {resolution.normalized}")
        self.resolution = resolution
        self.node = node
        self.from_material = from_material

    def detail(self) -> dict[str, Any]:
        """The body of the 404, alike for every endpoint: why, the resolution and, for a material, its search."""
        body: dict[str, Any] = {"message": NOT_FOUND, "resolution": self.resolution.model_dump()}
        if self.node is not None:
            body["node_article"] = node_block(self.node)
            if self.from_material and self.node.named == "":
                body["message"] = NO_SUBJECT_TOPIC
            elif self.from_material:
                body["message"] = NO_ARTICLE_AFTER_LLM if self.node.calls else NO_MATERIAL_ARTICLE
        return body


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
    subjects: list[str] = field(default_factory=list)  # all of equal weight (D45)
    collection: CollectionInfo | None = None
    node: NodeInput | None = None  # the node the topic came from (D45)
    knowledge: dict[str, Any] | None = None
    chunks_truncated: int = 0  # paragraphs the CORPUS_MAX_CHUNKS cap left out
    subtopics: list[str] = field(default_factory=list)  # part 2 keywords from the whole corpus, before the cap
    article_choice: ArticleChoiceReport | None = None  # article_choice=llm: what the model was asked and answered
    hit_check: HitCheckReport | None = None  # article_choice=llm: which side articles the model dropped
    side_articles: int = 0  # full-text hits and linked sub-articles build_corpus added, before any check
    node_article: NodeArticleReport | None = None  # how the article of a material was found (D47)
    material: str | None = None  # the material's own article beside the topic's, for the corpus (D47)

    @property
    def sources_by_id(self) -> dict[str, Source]:
        return {s.source_id: s for s in self.sources}


@dataclass
class Matched:
    matcher: str  # the strategy that decided: llm only when the model answered for at least one paragraph
    assignment: AssignmentResult
    duration_ms: int
    llm: LlmAssignmentReport | None = None  # matcher=llm: what the model decided and what it cost


@dataclass
class WorldPart:
    """Part 1 of one request: what was written, how, and what the audit reports about it."""

    matcher: str | None  # None when part 1 was not requested: no strategy ran
    matcher_requested: str | None  # the strategy the request asked for (or the default)
    extraction: str  # the switches in effect: rule-based when the LLM cannot be used
    generation: str
    enrichment: str  # sources-only unless an LLM actually writes blocks and the request allowed more
    llm_note: str | None
    chunks_assigned: int = 0
    extracted: ExtractionReport | None = None  # extraction=llm: what the LLM chose, per block
    regenerated: list[str] = field(default_factory=list)  # content blocks made anew despite an earlier text
    written: WrittenSections = field(default_factory=lambda: WrittenSections(sections=[], citations=[]))
    matching: LlmAssignmentReport | None = None  # matcher=llm: what the model decided


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
        self.repository_transport: httpx.BaseTransport | None = None  # tests answer other repositories offline
        self._foreign: dict[str, CollectionBuilder] = {}
        self._foreign_lock = threading.Lock()
        self.llm = llm
        self.writer = SectionWriter(facets, settings.facets_level, registry.lookup)
        # The subject's words pick the meaning of an ambiguous topic (config/subjects.yaml, kontext)
        self.subjects = (
            SubjectCatalog.load(settings.subjects_path) if settings.subjects_path.exists() else SubjectCatalog.empty()
        )
        try:  # at start: a wrong default is the operator's error, not a 422 for every request
            ensure_strategy(settings.matcher_default)
        except UnknownMatcherError as exc:
            known = ", ".join(STRATEGIES)
            raise ValueError(f"MATCHER_DEFAULT={settings.matcher_default!r} is not a strategy ({known})") from exc
        if settings.matcher_default == LLM_MATCHER:  # matcher=llm falls back on the default, which needs no b-api
            raise ValueError("MATCHER_DEFAULT=llm is not possible: the default strategy has to run without the b-api")

    def prepare(
        self, request: GenerateRequest, deadline: Deadline | None = None, choice: ArticleChoiceJob | None = None
    ) -> PreparedTopic:
        """Resolve the topic, build the corpus and segment it: everything that precedes matching.

        Part 3 alone needs the collection only: its topic is resolved where possible, and no corpus is built.
        ``deadline`` bounds the repository reads of the knowledge collection; material texts not fetched in
        time are left out and counted in the audit. With ``choice`` the LLM decides an unsure article (D35).
        """
        self.subjects.check(request.subject)  # before any reading: a typo would otherwise count for nothing
        timings: dict[str, int] = {}
        lap = _Stopwatch(timings).lap

        template = self.templates.get(request.template_id or self.settings.template_default)
        if request.empty_slot_policy:
            template = template.model_copy(update={"empty_slot_policy": request.empty_slot_policy})
        lexicon = self.lexicon.with_template(template)

        collection = self._collection_info(request)
        node_info, node = self.read_node(request.node_id, request.repository) if request.node_id else (None, None)
        derived: list[CollectionTopic] = []
        if node_info is not None:
            derived.append(node_topic(node_info))
        if collection is not None:
            derived.append(collection_topic(collection))
        # Part 1 and part 2 build on the corpus; part 3 alone, or with an unconfigured part 2, does not, and needs
        # no LLM to choose an article it will not read
        needs_corpus = "world" in request.parts or ("curricula" in request.parts and self.curricula is not None)
        chosen = choose_main_article(
            self.registry,
            self.subjects,
            request.topic,
            derived,
            subject=request.subject,
            node=node_info,
            job=choice if needs_corpus else None,
        )
        resolution = chosen.resolution
        if not resolution.resolved and needs_corpus:
            raise TopicNotFoundError(resolution, chosen.node, from_material=not request.topic)
        lap("resolve")
        prepared = PreparedTopic(
            template=template,
            lexicon=lexicon,
            normalized=chosen.normalized,
            resolution=resolution,
            sources=[],
            chunks=[],
            timings=timings,
            subjects=chosen.subjects,
            collection=collection,
            node=node,
            article_choice=chosen.choice,
            node_article=chosen.node,
            material=chosen.material,
        )
        if needs_corpus:
            self._add_corpus(prepared, request, deadline, choice)
        return prepared

    def _add_corpus(
        self,
        prepared: PreparedTopic,
        request: GenerateRequest,
        deadline: Deadline | None,
        choice: ArticleChoiceJob | None = None,
    ) -> None:
        """The articles of the topic, the sub-topics and, for part 1, the knowledge collection and the capped chunks.

        With ``choice`` the model drops the side articles that do not fit the topic (D35, M25). The article of a
        material sent along with a topic joins when it links with the main article (D47).
        """
        lap = _Stopwatch(prepared.timings).lap
        sources = self.registry.build_corpus(
            prepared.resolution,
            slots=prepared.template.content_slots(),
            max_articles=request.max_articles or self.settings.corpus_max_articles,
            material=prepared.material,
        )
        if prepared.node_article is not None:
            prepared.node_article.added = any(s.origin == NODE_ORIGIN for s in sources)
        lap("corpus")
        prepared.side_articles = sum(1 for s in sources if s.origin in CHECKED_ORIGINS)
        if choice is not None and prepared.side_articles:
            topic = prepared.resolution.title or prepared.normalized.topic
            gone, prepared.hit_check = check_hits(choice, topic, sources)
            sources = [s for s in sources if s.source_id not in gone]
            lap("hit_check")
        # The materials are sources of part 1 only; without it their texts would be read and thrown away
        if request.knowledge_collection_id and "world" in request.parts:
            if self.collections is None:
                knowledge_id = request.knowledge_collection_id
                prepared.knowledge = {"collection_id": knowledge_id, "error": NO_REPOSITORY, "sources": 0}
            else:
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
        if not request.collection_id:
            return None
        if self.collections is None:
            if request.topic or request.node_id:  # part 3 says it is unavailable; the topic comes from elsewhere
                return None
            raise RepositoryUnavailableError(NO_REPOSITORY)
        try:
            return self.collections.info(request.collection_id)
        except CollectionNotFoundError:
            raise
        except EduSharingError as exc:
            if request.topic or request.node_id:  # the topic comes from the request or from the node
                log.warning("collection %s not readable, continuing without it: %s", request.collection_id, exc)
                return None
            raise

    def read_node(self, node_id: str, repository: str | None = None) -> tuple[NodeInfo, NodeInput]:
        """The metadata of a material or a collection (D45), from the configured repository or another allowed one.

        Raises ``RepositoryNotAllowedError`` for an address outside the allowlist, ``NodeNotFoundError`` for an
        unknown node, ``EduSharingError`` when the repository fails, ``RepositoryUnavailableError`` without one.
        """
        root, builder = self._node_repository(repository)
        info = builder.node(node_id)
        return info, node_input(info, root)

    def _node_repository(self, repository: str | None) -> tuple[str, CollectionBuilder]:
        """The REST root and the reader of a repository: the configured one, or one without credentials for any other.

        Nodes are read without credentials from either (``EduSharingClient.node``); an empty address names none.
        """
        base = self.settings.edu_sharing_base_url.rstrip("/")
        if not repository:
            if self.collections is None or not base:
                raise RepositoryUnavailableError(f"{NO_REPOSITORY}; repository angeben")
            return base, self.collections
        root = repository_root(repository, self.settings.edu_sharing_allowed_hosts)
        if self.collections is not None and base and urlsplit(root).hostname == urlsplit(base).hostname:
            return root, self.collections
        with self._foreign_lock:
            builder = self._foreign.get(root)
            if builder is None:
                # No credentials: those of the configured repository must never travel to another one
                client = EduSharingClient(
                    root, timeout_s=self.settings.edu_sharing_timeout_s, transport=self.repository_transport
                )
                shared = self.collections  # the same cache and cache time as the configured repository
                options = shared.options if shared is not None else CollectionOptions()
                builder = CollectionBuilder(client=client, cache=shared.cache if shared else None, options=options)
                self._foreign[root] = builder
        return root, builder

    def close(self) -> None:
        """Close the clients of other repositories; the configured one belongs to the app (``close_clients``)."""
        with self._foreign_lock:
            for builder in self._foreign.values():
                builder.client.close()
            self._foreign.clear()

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
        *,
        budget: RequestBudget | None = None,
        deadline: Deadline | None = None,
    ) -> Matched:
        """Score and assign the prepared chunks with one matching strategy.

        ``llm`` runs the default strategy and lets the model decide on top (D34); ``budget`` and ``deadline`` bound
        its calls, and a budget of its own is opened when none is given (evaluation).
        """
        name = matcher_name or self.settings.matcher_default
        if name == LLM_MATCHER:
            return self._match_with_llm(prepared, target_length, budget, deadline)
        started = time.perf_counter()
        matcher = get_matcher(name, self.settings.model2vec_path)
        fused = matcher.score(prepared.template.slots, prepared.chunks)
        fused = smooth_sections(fused, prepared.chunks, self.settings.policy_section_smoothing)
        assignment = self._assign(prepared, fused, target_length)
        duration_ms = int((time.perf_counter() - started) * 1000)
        return Matched(matcher=name, assignment=assignment, duration_ms=duration_ms)

    def _match_with_llm(
        self, prepared: PreparedTopic, target_length: int, budget: RequestBudget | None, deadline: Deadline | None
    ) -> Matched:
        """matcher=llm: the default strategy decides first; without a usable LLM its result is the answer."""
        started = time.perf_counter()
        base = self.match(prepared, self.settings.matcher_default, target_length)
        if self.llm is None or self.llm_unavailable() is not None:
            return base
        job = AssignmentJob(
            client=self.llm.client,
            budget=budget if budget is not None else self.llm.open_budget(),
            topic=prepared.resolution.title or prepared.normalized.topic,
            concurrency=self.llm.options.concurrency,
            deadline=deadline,
        )
        template = _scale_budgets(prepared.template, target_length)
        assignment, report = assign_with_llm(template, prepared.chunks, prepared.sources_by_id, base.assignment, job)
        duration_ms = int((time.perf_counter() - started) * 1000)
        matcher = LLM_MATCHER if report.answered else base.matcher
        return Matched(matcher=matcher, assignment=assignment, duration_ms=duration_ms, llm=report)

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
        # article_choice=llm (D35) needs the LLM before anything else; then the request's one budget opens here
        choice_requested, choice_note, choice = self.article_choice_job(request.article_choice, deadline)
        budget = choice.budget if choice is not None else None
        prepared = self.prepare(request, deadline, choice)
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
            world = self._world_part(prepared, request, switches, deadline, timings, budget)
        else:  # no matching, no synthesis, no LLM work
            world = WorldPart(
                matcher=None,
                matcher_requested=None,
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
                subjects=prepared.subjects,
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
        hit_check, node_report = prepared.hit_check, prepared.node_article
        named_by_llm = node_report is not None and node_report.way == "llm"
        article_choice_used = choice_used(resolution.method == CHOSEN_BY_LLM or named_by_llm, hit_check)
        llm_audit, llm_tokens, llm_front = build_llm_report(
            self.llm,
            extraction_requested=extraction_requested,
            extraction_used=extraction_used,
            generation_requested=generation_requested,
            generation_used=generation_used,
            enrichment_requested=enrichment_requested,
            enrichment_used=enrichment_used,
            matching_requested="llm" if world.matcher_requested == LLM_MATCHER else "rule-based",
            matching_used="llm" if matcher_name == LLM_MATCHER else "rule-based",
            note=world.llm_note or choice_note,
            extraction=extracted,
            generation=drafted,
            matching=world.matching,
            choice_requested=choice_requested,
            choice_used=article_choice_used,
            choice=prepared.article_choice,
            choice_chosen=resolution.title if resolution.method == CHOSEN_BY_LLM else None,
            # the model is asked for an unsure article (a chosen one stays unsure) and for side articles
            choice_needed=not resolution.confident or prepared.side_articles > 0 or node_report is not None,
            hit_check=hit_check,
            node=node_report,
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
                "method": resolution.method,
                "confident": resolution.confident,
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
            matcher_requested=world.matcher_requested,
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
            include_frontmatter=request.frontmatter_in_markdown,
        )
        lap("assemble")

        filled = sum(1 for s in sections if s.status is not SectionStatus.EMPTY)
        parts_status = _parts_status(request, want_world, filled, curricula, collection_part)
        audit = AuditReport(
            preset=request.preset,
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
            node_article=node_block(node_report) if node_report is not None else None,
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
            node=prepared.node,
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
        shared_budget: RequestBudget | None = None,
    ) -> WorldPart:
        """Part 1: match the chunks (with matcher=llm the model assigns them, D34), let the LLM choose sentences and
        write blocks as the switches ask (D33).

        ``requested`` holds the extraction, the generation and the enrichment switch; without a usable LLM
        the first two run rule-based and nothing is enriched. ``shared_budget`` is the request's budget when the
        article choice opened it already.
        """
        extraction_wanted, generation_wanted, enrichment_wanted = requested
        matcher_wanted = request.matcher or self.settings.matcher_default
        wants_llm = (
            extraction_wanted != "rule-based" or generation_wanted != "rule-based" or matcher_wanted == LLM_MATCHER
        )
        llm_note = self.llm_unavailable() if wants_llm else None
        extraction, generation = ("rule-based", "rule-based") if llm_note else (extraction_wanted, generation_wanted)
        enrichment = "sources-only" if generation == "rule-based" else enrichment_wanted
        llm = self.llm if wants_llm and llm_note is None else None
        # one budget for all LLM work of the request
        budget = (shared_budget or llm.open_budget()) if llm is not None else None
        matched = self.match(prepared, request.matcher, request.target_length, budget=budget, deadline=deadline)
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
        ai_assigned = {  # blocks holding paragraphs the model assigned: marked as chosen by an AI
            slot_id
            for slot_id, items in matched.assignment.assigned.items()
            if any(item.matcher == LLM_ASSIGNED for item in items)
        }
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
            ai_assigned=ai_assigned,
            preserved=preserved,
        )
        lap("synthesize")
        return WorldPart(
            matcher=matched.matcher,
            matcher_requested=matcher_wanted,
            extraction=extraction,
            generation=generation,
            enrichment=enrichment,
            llm_note=llm_note,
            chunks_assigned=sum(len(v) for v in assigned.values()),
            extracted=extracted,
            written=written,
            matching=matched.llm,
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

    def article_choice_job(
        self, requested: str | None, deadline: Deadline | None
    ) -> tuple[str, str | None, ArticleChoiceJob | None]:
        """The article choice in effect, why the LLM cannot make it, and the job when it can (D35, D37, D40).

        The shipped default is ``rule-based`` (D40). A default of ``llm`` (LLM_ARTICLE_CHOICE_DEFAULT) only applies
        where an LLM is configured; without one the rules choose and nothing is noted, so a service without a b-api
        does not report a missing LLM in every answer. A request that asks for ``llm`` itself, directly or through
        a preset, gets the note.
        """
        default = self.settings.llm_article_choice_default if self.llm is not None else "rule-based"
        wanted = requested or default
        if wanted != "llm":
            return wanted, None, None
        note = self.llm_unavailable()
        if note is not None or self.llm is None:
            return wanted, note, None
        return wanted, None, ArticleChoiceJob(self.llm.client, self.llm.open_budget(), deadline)

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


# Which paragraphs survive CORPUS_MAX_CHUNKS: the topic's own articles, then the materials the request asked for and
# the article of its node, then the neighbours found by links and search. Anything else (lookups) comes last.
ORIGIN_PRIORITY = {"primary": 0, "same_topic": 1, "material": 2, NODE_ORIGIN: 2, "linked": 3, "search": 4}


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
        if not source.is_primary
        and source.origin in {"same_topic", NODE_ORIGIN, "linked"}
        and stem in source.title.lower()
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
