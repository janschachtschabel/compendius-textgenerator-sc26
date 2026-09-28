"""What the steps of a compendium hand on: the prepared topic, the matching, the parts (PLAN.md 3.1)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import Chunk, CollectionPart, CurriculaPart, NodeInput, Resolution, Source, primary_of
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import ArticleChoiceReport, HitCheckReport
from app.knowledge.curriculum_check import CurriculumCheckReport
from app.knowledge.node_article import NodeArticleReport
from app.knowledge.topic import NormalizedTopic
from app.knowledge.topic_articles import TopicArticlesReport
from app.matching.lexicon import HeadingLexicon
from app.matching.llm_assignment import LlmAssignmentReport
from app.matching.policy import AssignmentResult
from app.sources.wlo.models import CollectionInfo
from app.synthesis.extraction import ExtractionReport
from app.synthesis.writer import WrittenSections
from app.templates.schema import Template


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
    articles: TopicArticlesReport | None = None  # article_choice=llm: the overview and parts the model named (D63)
    side_articles: int = 0  # full-text hits and linked sub-articles build_corpus added, before any check
    node_article: NodeArticleReport | None = None  # how the article of a material was found (D47)
    material: str | None = None  # the material's own article beside the topic's, for the corpus (D47)

    @property
    def sources_by_id(self) -> dict[str, Source]:
        return {s.source_id: s for s in self.sources}

    @property
    def title(self) -> str:
        """The article the topic resolved to, or the normalized topic where none was needed (part 3 alone)."""
        return self.resolution.title or self.normalized.topic

    @property
    def primary(self) -> Source | None:
        """The main article of the corpus, or its first source."""
        return primary_of(self.sources)

    @property
    def aliases(self) -> list[str]:
        """The other names of the main article, which part 2 searches for as well."""
        primary = self.primary
        return list(primary.aliases) if primary else []


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

    @classmethod
    def skipped(cls) -> WorldPart:
        """Part 1 not requested: no matching, no synthesis, no LLM work."""
        return cls(
            matcher=None,
            matcher_requested=None,
            extraction="rule-based",
            generation="rule-based",
            enrichment="sources-only",
            llm_note=None,
        )


@dataclass(frozen=True)
class Requested:
    """The switches of part 1 as the request or its profile set them (with_profile), before the LLM had its say."""

    extraction: str
    generation: str
    enrichment: str

    @classmethod
    def of(cls, request: GenerateRequest) -> Requested:
        """The switches describe how part 1 is made; parts 2 and 3 alone are rule-based by definition."""
        if "world" not in request.parts:
            return cls("rule-based", "rule-based", "sources-only")
        return cls(
            request.extraction or "rule-based", request.generation or "rule-based", request.enrichment or "sources-only"
        )


@dataclass
class CurriculaResult:
    """Part 2 of one request, and what the LLM check of D58 did for it."""

    part: CurriculaPart | None  # None when not requested or not set up here
    requested: str  # curriculum_check as the request or its profile set it
    report: CurriculumCheckReport | None = None  # what the check did, once it ran
    fallback: str | None = None  # why the rules decided instead of the LLM


@dataclass
class Made:
    """What a request made, handed to the assembly: the topic, the parts and how the article was chosen."""

    prepared: PreparedTopic
    world: WorldPart
    requested: Requested
    choice_requested: str  # article_choice as asked (D35)
    choice_note: str | None  # why the LLM could not choose
    curricula: CurriculaResult
    collection: CollectionPart | None
    facets_visible: bool
    timings: dict[str, int]


class Stopwatch:
    """Writes the milliseconds since the previous lap into ``timings``."""

    def __init__(self, timings: dict[str, int]) -> None:
        self._timings = timings
        self._started = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self._timings[name] = int((now - self._started) * 1000)
        self._started = now
