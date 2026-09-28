"""Orchestrator for part 1 (PLAN.md 3.1): resolve, corpus, segment, match, synthesise, assemble."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

import httpx

from app.compendium.corpus import segment_corpus, subtopics
from app.compendium.errors import (
    NO_REPOSITORY,
    PartsUnavailableError,
    TopicNotFoundError,
)
from app.compendium.llm_policy import choice_audit, llm_switches
from app.compendium.prepared import PreparedTopic, Stopwatch, WorldPart
from app.compendium.repository import RepositoryReading
from app.compendium.world import WorldBuilding
from app.compose.assembler import build_frontmatter, render_markdown
from app.compose.regeneration import check_names
from app.domain.models import (
    AuditReport,
    CollectionPart,
    Compendium,
    CurriculaPart,
    SectionStatus,
)
from app.domain.requests import GenerateRequest, with_profile
from app.knowledge.article_choice import (
    CHECKED_ORIGINS,
    ArticleChoiceJob,
    check_hits,
)
from app.knowledge.curriculum_check import CurriculumCheckReport
from app.knowledge.main_article import choose_main_article
from app.knowledge.node_article import node_block
from app.knowledge.topic_articles import settle
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.llm.gateway import LlmGateway
from app.llm.report import build_llm_report
from app.matching.lexicon import HeadingLexicon
from app.matching.registry import LLM_MATCHER, ensure_strategy
from app.settings import Settings
from app.sources.lehrplan.part import CurriculaBuilder
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.wlo.part import (
    CollectionBuilder,
    CollectionTopic,
    collection_topic,
    node_topic,
)
from app.sources.zim.registry import NODE_ORIGIN, ZimRegistry
from app.synthesis.facets import FacetCatalog
from app.synthesis.lint import lint_sections
from app.synthesis.writer import SectionWriter
from app.templates.manager import TemplateManager

log = logging.getLogger(__name__)


class CompendiumService(RepositoryReading, WorldBuilding):
    """A compendium from a request (PLAN.md 3.1): prepare the topic and its corpus, make the requested parts and
    assemble them. Reading the repositories, the LLM's policy and part 1 are its mixins in app/compendium/.
    """

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

    def prepare(
        self,
        request: GenerateRequest,
        deadline: Deadline | None = None,
        choice: ArticleChoiceJob | None = None,
        *,
        registry: ZimRegistry | None = None,
        segment: bool = True,
    ) -> PreparedTopic:
        """Resolve the topic, build the corpus and segment it: everything that precedes matching.

        Part 3 alone needs the collection only: its topic is resolved where possible, and no corpus is built.
        ``deadline`` bounds the repository reads of the knowledge collection; material texts not fetched in
        time are left out and counted in the audit. With ``choice`` the LLM decides an unsure article (D35).
        ``registry`` narrows the archives (/knowledge asks some of them); ``segment=False`` keeps the articles whole,
        as /knowledge returns them - the one way to a topic's corpus for a compendium, the curriculum search and
        /knowledge (audit 2026-09-27, AR-02).
        """
        self.subjects.check(request.subject)  # before any reading: a typo would otherwise count for nothing
        timings: dict[str, int] = {}
        lap = Stopwatch(timings).lap

        template = self.templates.get(request.template_id or self.settings.template_default)
        check_names(request.regenerate_sections, template)
        if request.empty_slot_policy:
            template = template.model_copy(update={"empty_slot_policy": request.empty_slot_policy})
        lexicon = self.lexicon.with_template(template)

        collection = self._collection_info(request)
        knowledge_failure = self._probe_knowledge(request.knowledge_collection_id)
        node_info, node = self.read_node(request.node_id, request.repository) if request.node_id else (None, None)
        derived: list[CollectionTopic] = []
        if node_info is not None:
            derived.append(node_topic(node_info))
        if collection is not None:
            derived.append(collection_topic(collection))
        needs_corpus = self._needs_corpus(request)
        registry = registry or self.registry
        chosen = choose_main_article(
            registry,
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
            articles=chosen.articles,
            node_article=chosen.node,
            material=chosen.material,
            knowledge=knowledge_failure,  # a repository that failed on the probe is not asked again
        )
        if needs_corpus:
            self._add_corpus(prepared, request, deadline, choice, registry, segment)
        return prepared

    def _needs_corpus(self, request: GenerateRequest) -> bool:
        """Part 1 and part 2 build on the corpus; part 3 alone, or with an unconfigured part 2, does not, and needs
        no LLM to choose an article it will not read."""
        return "world" in request.parts or ("curricula" in request.parts and self.curricula is not None)

    def _add_corpus(
        self,
        prepared: PreparedTopic,
        request: GenerateRequest,
        deadline: Deadline | None,
        choice: ArticleChoiceJob | None,
        registry: ZimRegistry,
        segment: bool,
    ) -> None:
        """The articles of the topic, the sub-topics and, for part 1, the knowledge collection and the capped chunks.

        With ``choice`` the articles the model named for the topic are the side articles (D63); without them it drops
        the side articles that do not fit the topic (D35, M25). The article of a material sent along with a topic
        joins when it links with the main article (D47).
        """
        lap = Stopwatch(prepared.timings).lap
        sources = registry.build_corpus(
            prepared.resolution,
            slots=prepared.template.content_slots(),
            max_articles=request.max_articles or self.settings.corpus_max_articles,
            material=prepared.material,
            named=prepared.articles.found if prepared.articles is not None else (),
        )
        if prepared.articles is not None:
            settle(prepared.articles, sources)
        if prepared.node_article is not None:
            prepared.node_article.added = any(s.origin == NODE_ORIGIN for s in sources)
        lap("corpus")
        prepared.side_articles = sum(1 for s in sources if s.origin in CHECKED_ORIGINS)
        if choice is not None and prepared.side_articles:
            gone, prepared.hit_check = check_hits(choice, prepared.title, sources)
            sources = [s for s in sources if s.source_id not in gone]
            lap("hit_check")
        # The materials are sources of part 1 only (the request refuses them without it); a failed probe already
        # put its error in the audit
        if request.knowledge_collection_id and "world" in request.parts and prepared.knowledge is None:
            if self.collections is None:
                knowledge_id = request.knowledge_collection_id
                prepared.knowledge = {"collection_id": knowledge_id, "error": NO_REPOSITORY, "sources": 0}
            else:
                prepared.knowledge = self._knowledge(request.knowledge_collection_id, sources, deadline)
                lap("knowledge")

        # The cap only decides which paragraphs part 1 uses; part 2 searches for every neighbour of the corpus.
        primary = next((s for s in sources if s.is_primary), sources[0] if sources else None)
        prepared.subtopics = subtopics(sources, primary)
        if "world" not in request.parts or not segment:  # paragraphs and their cap serve part 1 only
            prepared.sources = sources
            return
        prepared.chunks, prepared.sources, prepared.chunks_truncated = segment_corpus(
            sources, prepared.lexicon, self.settings.corpus_max_chunks
        )
        lap("segment")

    def generate(
        self, request: GenerateRequest, *, deadline: Deadline | None = None, budget: RequestBudget | None = None
    ) -> Compendium:
        """The compendium of a request. ``deadline`` and ``budget`` let a caller spend one time and one token budget
        over more than the compendium, as /qa does for part 1 and its pairs; without them the request opens its own."""
        if deadline is None:  # bounds the LLM work; the rule-based path needs none
            deadline = Deadline(self.settings.request_timeout_s)
        defaulted = request.preset is None
        profile = request.preset or self.settings.preset_default
        request = with_profile(request, profile)
        if request.matcher:  # before any work
            ensure_strategy(request.matcher)
        self.refuse_without_llm(llm_switches(request, corpus=self._needs_corpus(request)), profile, defaulted)
        unmakeable = self._unmakeable(request)
        if len(unmakeable) == len(set(request.parts)):  # an empty compendium would look like a success
            raise PartsUnavailableError("; ".join(unmakeable.values()))
        # The request's one budget, the profile's size (D59), unless the caller brought one to share over more than
        # the compendium (/qa); article_choice=llm (D35) spends from it first
        if budget is None:
            budget = self.open_budget(profile)
        choice_requested, choice_note, choice = self.article_choice_job(request.article_choice, deadline, budget)
        budget = choice.budget if choice is not None else budget
        prepared = self.prepare(request, deadline, choice)
        want_world = "world" in request.parts
        # The switches and the matcher describe how part 1 is made; parts 2 and 3 alone are rule-based by definition
        extraction_requested = request.extraction or "rule-based"  # set by the profile (with_profile)
        generation_requested = request.generation or "rule-based"
        enrichment_requested = request.enrichment or "sources-only"
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
        lap = Stopwatch(timings).lap

        template, sources, chunks = prepared.template, prepared.sources, prepared.chunks
        resolution = prepared.resolution
        sections, citations, matcher_name = world.written.sections, world.written.citations, world.matcher
        facets_visible = self._facets_visible(request)
        topic = prepared.title

        curricula: CurriculaPart | None = None
        curriculum_requested = request.curriculum_check or "rule-based"  # set by the profile (with_profile)
        checked: list[CurriculumCheckReport] = []  # what the LLM check did, once it ran
        curriculum_fallback: str | None = None
        if "curricula" in request.parts and self.curricula is not None:
            check = None
            if curriculum_requested == "llm":
                check, curriculum_fallback = self.curriculum_check(topic, prepared.subjects, budget, deadline, checked)
            curricula = self.curricula.build(
                title=topic,
                aliases=prepared.aliases,
                subtopics=prepared.subtopics,
                subjects=prepared.subjects,
                facets_visible=facets_visible,
                check=check,
            )
            if checked:
                report = checked[0]
                curricula.summary["llm_check"] = {
                    "rated": report.rated,
                    "answered": report.answered,
                    "dropped": report.dropped,
                    "fallbacks": dict(report.fallbacks),
                }
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
        node_report = prepared.node_article
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
            **choice_audit(prepared, choice_requested),
            curriculum_requested=curriculum_requested if curricula is not None else "rule-based",
            curriculum=checked[0] if checked else None,
            curriculum_fallback=curriculum_fallback,
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
