"""The article a request builds on, from its topic, its node or both (D12, D45, D47).

One place for the compendium and /knowledge, so both name the same article for the same request:

- a topic, or a collection whose title serves as one: the rules resolve it, and with article_choice llm the LLM
  decides where they are unsure (D35);
- a material without a topic: its title is often a format, not a subject, so the article comes from the rules over
  its title and description (``rule_article``) or, with article_choice llm, from the LLM (``ask_topic``);
- a topic and a material: the topic leads. The rules resolve it and name the material's own article; with
  article_choice llm one question hears both and names both, and the model may overrule the topic. The material's
  own article joins the corpus when it links with the main article (ZimRegistry.build_corpus).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from app.domain.models import Resolution
from app.knowledge.article_choice import (
    NAMED_TITLE_MISSING,
    ArticleChoiceJob,
    ArticleChoiceReport,
    LlmArticleChooser,
)
from app.knowledge.node_article import NodeArticleReport, ask_topic, ranked_entities, rule_article
from app.knowledge.topic import NormalizedTopic, normalize_topic
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.wlo.models import NodeInfo
from app.sources.wlo.part import CollectionTopic, DerivedTopic, derive_topic
from app.sources.zim.registry import ZimRegistry


@dataclass
class MainArticle:
    """The article a request builds on, and how it was found."""

    normalized: NormalizedTopic
    subjects: list[str]  # all of equal weight
    context: list[str]
    resolution: Resolution
    choice: ArticleChoiceReport | None = None  # the LLM deciding an unsure topic (D35)
    node: NodeArticleReport | None = None  # how a material's article was found (D47)
    material: str | None = None  # the material's own article beside the topic's, for the corpus


def choose_main_article(
    registry: ZimRegistry,
    catalog: SubjectCatalog,
    topic: str | None,
    derived: Sequence[CollectionTopic],
    *,
    subject: str | None = None,
    node: NodeInfo | None = None,
    job: ArticleChoiceJob | None = None,
) -> MainArticle:
    """The article for the topic, the node and the collection of a request; ``job`` is article_choice=llm."""
    found = derive_topic(topic, derived, subject)
    terms = catalog.context_terms_of(found.subjects)
    around = [word for entry in derived for word in entry.context]  # the words the node and the collection bring

    def by_rules(title: str) -> Resolution:
        normalized = normalize_topic(title)
        context = [*normalized.context, *around]
        return registry.resolve_topic(normalized.topic, context=context, query=found.normalized.query, terms=terms)

    def as_found(
        resolution: Resolution,
        choice: ArticleChoiceReport | None = None,
        report: NodeArticleReport | None = None,
        material: str | None = None,
    ) -> MainArticle:
        normalized = found.normalized
        if report is not None and not topic and resolution.resolved:  # the material's topic is the article found
            normalized = replace(normalized, topic=resolution.normalized)
        return MainArticle(normalized, found.subjects, found.context, resolution, choice, report, material)

    def the_topic() -> tuple[Resolution, ArticleChoiceReport | None]:
        chooser = LlmArticleChooser(job, found.normalized.topic, catalog.labels_of(found.subjects)) if job else None
        resolution = registry.resolve_topic(
            found.normalized.topic,
            context=found.context,
            query=found.normalized.query,
            terms=terms,
            chooser=chooser,
        )
        return resolution, chooser.report if chooser is not None else None

    if node is None or node.kind != "material":
        resolution, choice = the_topic()
        return as_found(resolution, choice=choice)

    report = NodeArticleReport()
    answer = ask_topic(job, node, report, topic=topic) if job is not None else None
    if answer is not None:
        named, own = answer
        if not named and not topic:  # the model sees no subject topic in the material
            return as_found(_none(found), report=report)
        answered = by_rules(named) if named else None
        if answered is not None and answered.resolved:
            report.material = by_rules(own).title if own else None
            return as_found(answered, report=report, material=report.material)
        if named:
            report.fallback = NAMED_TITLE_MISSING
    report.way = "rules"
    rules = _by_the_rules(registry, node, by_rules, report)
    if not topic:
        return as_found(rules or _none(found), report=report)
    resolution, choice = the_topic()
    report.material = rules.title if rules is not None else None
    return as_found(resolution, choice, report, report.material)


def _by_the_rules(
    registry: ZimRegistry, node: NodeInfo, by_rules: Callable[[str], Resolution], report: NodeArticleReport
) -> Resolution | None:
    """The article the rules find for a material (M23), or ``None``; the report gets the title's article and terms."""
    titled = by_rules(node.title)
    report.title_article = titled.title
    report.entities = ranked_entities(registry.archives, node.title, node.description, node.keywords)
    pick = rule_article(titled.title, report.entities, node.title)
    if pick is None:
        return None
    return titled if pick == titled.title else by_rules(pick)


def _none(found: DerivedTopic) -> Resolution:
    """No article: the resolution shows what came in and nothing else."""
    return Resolution(query=found.normalized.query, normalized=found.normalized.topic, context=list(found.context))
