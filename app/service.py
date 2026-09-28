"""The compendium service (PLAN.md 3.1): prepare the topic and its corpus, make the requested parts, assemble them.

Its parts live in app/compendium/: the refusals, what the steps hand on, the corpus rules, the LLM's policy, the
repository reading, part 1 and the assembly (audit 2026-09-27, AR-01).
"""

from __future__ import annotations

import logging
import threading

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
from app.compendium.prepared import CurriculaResult, Made, PreparedTopic, Requested, Stopwatch, WorldPart
from app.compendium.repository import RepositoryReading
from app.compendium.world import WorldBuilding
from app.compose.regeneration import check_names
from app.domain.models import (
    CollectionPart,
    Compendium,
    primary_of,
)
from app.domain.requests import GenerateRequest, with_profile
from app.knowledge.article_choice import (
    CHECKED_ORIGINS,
    ArticleChoiceJob,
    check_hits,
)
from app.knowledge.curriculum_check import CurriculumCheckReport
from app.knowledge.main_article import choose_main_article
from app.knowledge.topic_articles import settle
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.matching.lexicon import HeadingLexicon
from app.matching.registry import ensure_strategy
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
        self, request: GenerateRequest, *, deadline: Deadline | None = None, budget: RequestBudget | None = None
    ) -> Compendium:
        """The compendium of a request. ``deadline`` and ``budget`` let a caller spend one time and one token budget
        over more than the compendium, as /qa does for part 1 and its pairs; without them the request opens its own."""
        if deadline is None:  # bounds the LLM work; the rule-based path needs none
            deadline = Deadline(self.settings.request_timeout_s)
        request, profile = self._admit(request)
        # The request's one budget, the profile's size (D59), unless the caller brought one to share over more than
        # the compendium (/qa); article_choice=llm (D35) spends from it first
        if budget is None:
            budget = self.open_budget(profile)
        choice_requested, choice_note, choice = self.article_choice_job(request.article_choice, deadline, budget)
        budget = choice.budget if choice is not None else budget
        prepared = self.prepare(request, deadline, choice)
        requested = Requested.of(request)
        timings = dict(prepared.timings)
        if "world" in request.parts:
            world = self._world_part(prepared, request, requested, deadline, timings, budget)
        else:  # no matching, no synthesis, no LLM work
            world = WorldPart.skipped()
        lap = Stopwatch(timings).lap
        curricula = self._curricula_part(prepared, request, budget, deadline)
        if curricula.part is not None:
            lap("curricula")
        collection: CollectionPart | None = None
        if "collection" in request.parts and request.collection_id and self.collections is not None:
            collection = self._collection_part(request.collection_id, deadline)
            lap("collection")
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
        )
        return assemble(request, made, lap, llm=self.llm, facets=self.facets, zim_snapshot=self.registry.snapshot())

    def _admit(self, request: GenerateRequest) -> tuple[GenerateRequest, str]:
        """The request with the switches of its profile (D41) and the profile; refuses before any work what this
        server cannot make: an unknown strategy, a switch that needs an LLM it lacks (D53), no makeable part."""
        defaulted = request.preset is None
        profile = request.preset or self.settings.preset_default
        request = with_profile(request, profile)
        if request.matcher:
            ensure_strategy(request.matcher)
        self.refuse_without_llm(llm_switches(request, corpus=self._needs_corpus(request)), profile, defaulted)
        unmakeable = self._unmakeable(request)
        if len(unmakeable) == len(set(request.parts)):  # an empty compendium would look like a success
            raise PartsUnavailableError("; ".join(unmakeable.values()))
        return request, profile

    def _curricula_part(
        self, prepared: PreparedTopic, request: GenerateRequest, budget: RequestBudget | None, deadline: Deadline
    ) -> CurriculaResult:
        """Part 2 when requested and set up here, the curriculum elements checked by the LLM when curriculum_check
        asks for it (D58)."""
        requested = request.curriculum_check or "rule-based"  # set by the profile (with_profile)
        if "curricula" not in request.parts or self.curricula is None:
            return CurriculaResult(part=None, requested=requested)
        checked: list[CurriculumCheckReport] = []  # what the LLM check did, once it ran
        check, fallback = None, None
        if requested == "llm":
            check, fallback = self.curriculum_check(prepared.title, prepared.subjects, budget, deadline, checked)
        part = self.curricula.build(
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
        return CurriculaResult(part=part, requested=requested, report=report, fallback=fallback)

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
