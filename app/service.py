"""The compendium service (PLAN.md 3.1): prepare the topic and its corpus, make the requested parts, assemble them.

Its parts live in app/compendium/: the refusals, what the steps hand on, the corpus rules, the LLM's policy, the
repository reading, part 1 and the assembly (audit 2026-09-27, AR-01).
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from app.compendium.assembly import assemble
from app.compendium.corpus import segment_corpus, subtopics
from app.compendium.errors import (
    NO_REPOSITORY,
    PartsUnavailableError,
    TopicNotFoundError,
)
from app.compendium.gateway import LlmGateway
from app.compendium.llm_policy import llm_switches
from app.compendium.prepared import CurriculaResult, Made, PreparedTopic, Requested, Stopwatch, WorldPart, timed
from app.compendium.repository import RepositoryReading
from app.compendium.world import WorldBuilding
from app.compose.regeneration import check_names
from app.concurrency import Beside
from app.domain.models import (
    CollectionPart,
    Compendium,
    CurriculaPart,
    primary_of,
)
from app.domain.requests import PART_3_NEEDS_A_COLLECTION, GenerateRequest, with_profile
from app.knowledge.article_choice import (
    CHECKED_ORIGINS,
    ArticleChoiceJob,
    check_hits,
)
from app.knowledge.collection_context import describe, shown_topic
from app.knowledge.corpus_sources import NODE_ORIGIN, build_corpus
from app.knowledge.curriculum_check import CurriculumCheckReport
from app.knowledge.derived_topic import CollectionTopic, collection_topic, node_topic
from app.knowledge.lexicon import HeadingLexicon
from app.knowledge.main_article import choose_main_article
from app.knowledge.topic import topic_as_asked
from app.knowledge.topic_articles import settle
from app.knowledge.topic_wording import TopicWordingReport, word_topic, wording_request
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.matching.registry import ensure_strategy
from app.settings import Settings
from app.sources.lehrplan.part import CurriculaBuilder
from app.sources.lehrplan.render import render_failed
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.wlo.models import CollectionInfo, NodeInfo
from app.sources.wlo.part import CollectionBuilder
from app.sources.wlo.tree import TreeContext
from app.sources.zim.registry import ZimRegistry
from app.synthesis.facets import FacetCatalog
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
        wording: ArticleChoiceJob | None = None,
    ) -> PreparedTopic:
        """Resolve the topic, build the corpus and segment it: everything that precedes matching.

        Part 3 alone needs the collection only: its topic is resolved where possible, and no corpus is built.
        ``deadline`` bounds the repository reads, from the first (audit 2026-10-02, A08); material texts not
        fetched in time are left out and counted in the audit. With ``choice`` the LLM decides an unsure article (D35).
        ``registry`` narrows the archives (/knowledge asks some of them); ``segment=False`` keeps the articles whole,
        as /knowledge returns them - the one way to a topic's corpus for a compendium, the curriculum search and
        /knowledge (audit 2026-09-27, AR-02). With ``wording`` - a writing profile - the model words the topic of a
        text in place of a topic (D72).
        """
        self.subjects.check(request.subject)  # before any reading: a typo would otherwise count for nothing
        timings: dict[str, int] = {}
        lap = Stopwatch(timings).lap

        template = (
            self.templates.get(request.template_id)
            if request.template_id
            else self.templates.default(self.settings.template_default)
        )
        check_names(request.regenerate_sections, template)
        # before the archives and any model call: an earlier text that cannot be read or placed is refused for free
        # (F13); its blocks are part 1's, so a request without part 1 leaves it unread as before
        preserved = self._preserved(request, template) if "world" in request.parts else {}
        if request.empty_slot_policy:
            template = template.model_copy(update={"empty_slot_policy": request.empty_slot_policy})
        lexicon = self.lexicon.with_template(template)

        remaining = deadline.remaining if deadline is not None else None
        collection = self._collection_info(request, remaining)
        knowledge_failure = self._probe_knowledge(request.knowledge_collection_id, remaining)
        node_info, node = None, None
        if request.node_id:
            node_info, node = self.read_node(request.node_id, request.repository, remaining=remaining)
        derived: list[CollectionTopic] = []
        if node_info is not None:
            derived.append(node_topic(node_info))
        if collection is not None:
            derived.append(collection_topic(collection))
        needs_corpus = self._needs_corpus(request)

        def place(whole: bool) -> TreeContext | None:
            """Where the collection whose title is the topic stands in its topic tree (M71)."""
            return self.collection_tree(node_info, collection, request.repository, remaining=remaining, content=whole)

        # One view of the archives for the whole request: a reload between its steps left sources and snapshot
        # naming different files (audit 2026-09-29, A10)
        registry = (registry or self.registry).view()
        chosen = choose_main_article(
            registry,
            self.subjects,
            request.topic,
            derived,
            subject=request.subject,
            node=node_info,
            job=choice if needs_corpus else None,
            place=place,
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
            tree=chosen.tree,
            stand_in=chosen.stand_in,
            knowledge=knowledge_failure,  # a repository that failed on the probe is not asked again
            registry=registry,
            preserved=preserved,
        )
        self._ask_topic(prepared, request, node_info or collection, wording)
        if needs_corpus:
            self._add_corpus(prepared, request, deadline, choice, registry, segment)
        return prepared

    def _ask_topic(
        self,
        prepared: PreparedTopic,
        request: GenerateRequest,
        beside: NodeInfo | CollectionInfo | None,
        wording: ArticleChoiceJob | None,
    ) -> None:
        """The topic every prompt hears (D72; Jan: "eine verfälschung des themas ist generell nicht gut"): the topic as
        asked, for a material without a topic its article (D47), for a collection its title - one that names no
        subject matter with what stands in for it, "Grundlagen (Kernphysik)" (M71). A writing profile lets the model
        word the topic of a text in its place, of a node's metadata without a topic among them, a collection's with
        its place in the topic tree (``wording_request``); without its answer the topic stays."""
        if request.topic or prepared.node_article is None:
            prepared.asked_topic = shown_topic(topic_as_asked(prepared.normalized), prepared.stand_in)
        else:
            prepared.asked_topic = prepared.title
        tree = prepared.tree
        place = describe(tree, self.subjects.labels_of(prepared.subjects)) if tree is not None else ""
        wanted = wording_request(request.topic, beside, place) if wording is not None else None
        if wanted is None or wording is None:
            return
        prepared.wording = TopicWordingReport(source=wanted.source, reason=wanted.reason)
        worded = word_topic(wording, wanted.text, prepared.wording)
        if worded:
            prepared.asked_topic = worded

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
        sources = build_corpus(
            registry,
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
            gone, prepared.hit_check = check_hits(choice, prepared.prompt_topic, sources)
            sources = [s for s in sources if s.source_id not in gone]
            lap("hit_check")
        # The materials are sources of part 1 only (the request refuses them without it); a failed probe already
        # put its error in the audit
        if request.knowledge_collection_id and "world" in request.parts and prepared.knowledge is None:
            if self.collections is None:
                knowledge_id = request.knowledge_collection_id
                prepared.knowledge = {"collection_id": knowledge_id, "error": NO_REPOSITORY, "sources": 0}
            else:
                prepared.knowledge = self._knowledge(
                    request.knowledge_collection_id,
                    sources,
                    deadline,
                    depth=request.knowledge_depth,
                    fulltext=request.knowledge_fulltext,
                )
                lap("knowledge")

        # The cap only decides which paragraphs part 1 uses; part 2 searches for every neighbour of the corpus.
        primary = primary_of(sources)
        prepared.subtopics = subtopics(sources, primary)
        if "world" not in request.parts or not segment:  # paragraphs and their cap serve part 1 only
            prepared.sources = sources
            return
        prepared.chunks, prepared.sources, prepared.chunks_truncated = segment_corpus(
            sources, prepared.lexicon, self.settings.corpus_max_chunks
        )
        lap("segment")

    def generate(
        self,
        request: GenerateRequest,
        *,
        deadline: Deadline | None = None,
        budget: RequestBudget | None = None,
        block_budget_factor: float | None = None,
    ) -> Compendium:
        """The compendium of a request. ``deadline`` and ``budget`` let a caller spend one time and one token budget
        over more than the compendium, as /qa does for part 1 and its pairs; without them the request opens its own.
        ``block_budget_factor`` sets the factor on the blocks' budgets for this compendium in place of
        BLOCK_BUDGET_FACTOR, as /qa does to keep the templates' budgets (D102).

        Parts 2 and 3 are made beside part 1, which waits on the model longest (M75): part 3 needs nothing of the
        topic and starts at once, part 2 once the topic is prepared. A request that fails does not wait for them, and
        their time ends with it: they start no further call or read."""
        started = time.perf_counter()
        if deadline is None:  # bounds the LLM work; the rule-based path needs none
            deadline = Deadline(self.settings.request_time_limit_s)
        request, profile = self._admit(request, deadline)
        # The request's one budget, the profile's size (D59), unless the caller brought one to share over more than
        # the compendium (/qa); article_choice=llm (D35) spends from it first
        if budget is None:
            budget = self.open_budget(profile)
        beside_time = deadline.branch()
        with Beside(workers=2, on_failure=beside_time.expire) as beside:
            collection_job = None
            if "collection" in request.parts and request.collection_id and self.collections is not None:
                collection_job = beside.start(timed(self._collection_part), request.collection_id, beside_time)
            choice_requested, choice_note, choice = self.article_choice_job(request.article_choice, deadline, budget)
            budget = choice.budget if choice is not None else budget
            # the topic a writing profile words is the one of part 1; without it nothing is written about it (D72)
            writing = request.generation if "world" in request.parts else None
            wording = self.wording_job(writing, choice, deadline, budget)
            prepared = self.prepare(request, deadline, choice, wording=wording)
            curricula_job = beside.start(timed(self._curricula_part), prepared, request, beside_time)
            requested = Requested.of(request)
            timings = dict(prepared.timings)
            if "world" in request.parts:
                world = self._world_part(prepared, request, requested, deadline, timings, budget, block_budget_factor)
            else:  # no matching, no synthesis, no LLM work
                world = WorldPart.skipped()
            # each part's own time; the request's whole time is the audit's duration_ms
            curricula, curricula_ms = curricula_job.result()
            if curricula.part is not None:
                timings["curricula"] = curricula_ms
            collection: CollectionPart | None = None
            if collection_job is not None:
                collection, timings["collection"] = collection_job.result()
        made = Made(
            prepared=prepared,
            world=world,
            requested=requested,
            choice_requested=choice_requested,
            choice_note=choice_note,
            curricula=curricula,
            collection=collection,
            facets_visible=self._facets_visible(request),
            timings=timings,
            # of the request's budget and the check's own (D94)
            cached_tokens=(budget.cached_tokens if budget is not None else 0) + curricula.cached_tokens,
        )
        archives = prepared.registry or self.registry
        lap = Stopwatch(timings).lap  # the assembly's own time
        compendium = assemble(request, made, lap, llm=self.llm, facets=self.facets, zim_snapshot=archives.snapshot())
        compendium.audit.duration_ms = int((time.perf_counter() - started) * 1000)
        return compendium

    def _admit(self, request: GenerateRequest, deadline: Deadline) -> tuple[GenerateRequest, str]:
        """The request with the switches of its profile (D41) and the profile; refuses before any work what this
        server cannot make: an unknown strategy, a switch that needs an LLM it lacks (D53), no makeable part."""
        defaulted = request.preset is None
        profile = request.preset or self.default_preset
        request = self.collection_from_node(with_profile(request, profile), deadline.remaining)
        if request.matcher:
            ensure_strategy(request.matcher)
        self.refuse_without_llm(llm_switches(request, corpus=self._needs_corpus(request)), profile, defaulted)
        unmakeable = self._unmakeable(request)
        if len(unmakeable) == len(set(request.parts)):  # an empty compendium would look like a success
            raise PartsUnavailableError("; ".join(unmakeable.values()))
        return request, profile

    def _curricula_part(self, prepared: PreparedTopic, request: GenerateRequest, deadline: Deadline) -> CurriculaResult:
        """Part 2 when requested and set up here, the curriculum elements checked by the LLM when curriculum_check
        asks for it (D58), from a budget of its own (D94). An unexpected error leaves part 2 unavailable with its
        reason: it runs beside part 1 and threw a finished part 1 away with a 500 (review of 2026-10-08)."""
        requested = request.curriculum_check or "rule-based"  # set by the profile (with_profile)
        if "curricula" not in request.parts or self.curricula is None:
            return CurriculaResult(part=None, requested=requested)
        try:
            return self._checked_curricula(self.curricula, prepared, request, deadline, requested)
        except Exception as exc:
            log.exception("part 2 failed unexpectedly")
            error = f"unerwarteter Fehler ({type(exc).__name__})"
            failed = CurriculaPart(
                available=False, summary={"reason": "error", "error": error}, markdown=render_failed(error)
            )
            return CurriculaResult(part=failed, requested=requested)

    def _checked_curricula(
        self,
        curricula: CurriculaBuilder,
        prepared: PreparedTopic,
        request: GenerateRequest,
        deadline: Deadline,
        requested: str,
    ) -> CurriculaResult:
        checked: list[CurriculumCheckReport] = []  # what the LLM check did, once it ran
        check, fallback, check_budget = None, None, None
        if requested == "llm":
            check_budget = self.open_check_budget()
            check, fallback = self.curriculum_check(
                prepared.prompt_topic, prepared.subjects, check_budget, deadline, checked
            )
        part = curricula.build(
            title=prepared.title,
            aliases=prepared.aliases,
            subtopics=prepared.subtopics,
            subjects=prepared.subjects,
            facets_visible=self._facets_visible(request),
            check=check,
        )
        report = checked[0] if checked else None
        if report is not None:
            part.summary["llm_check"] = {
                "rated": report.rated,
                "answered": report.answered,
                "dropped": report.dropped,
                "fallbacks": dict(report.fallbacks),
            }
        cached = check_budget.cached_tokens if check_budget is not None else 0
        return CurriculaResult(part=part, requested=requested, report=report, fallback=fallback, cached_tokens=cached)

    def _unmakeable(self, request: GenerateRequest) -> dict[str, str]:
        """Requested parts this request cannot get from this server, with the reason."""
        reasons: dict[str, str] = {}
        if "curricula" in request.parts and self.curricula is None:
            reasons["curricula"] = "Teil 2 ist in diesem Dienst nicht eingerichtet"
        if "collection" in request.parts and self.collections is None:
            reasons["collection"] = "Teil 3 braucht ein edu-sharing-Repository (EDU_SHARING_BASE_URL)"
        elif "collection" in request.parts and not request.collection_id:
            reasons["collection"] = PART_3_NEEDS_A_COLLECTION
        return reasons
