"""The article a request builds on, from its topic, its node or both (D12, D45, D47).

One place for the compendium and /knowledge, so both name the same article for the same request:

- a topic, or a collection whose title serves as one: the rules resolve it, and with article_choice llm the LLM
  decides where they are unsure (D35). Before that the LLM names the topic's overview article and the articles on its
  parts (D63, ``ask_topic_articles``); the overview replaces the rules' article where they missed the topic, and the
  parts are the side articles of the corpus;
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
from app.knowledge.topic_articles import TopicArticlesReport, ask_topic_articles
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.wlo.models import NodeInfo
from app.sources.wlo.part import CollectionTopic, DerivedTopic, derive_topic
from app.sources.zim.registry import CHOSEN_BY_LLM, GUESSED, ZimRegistry


@dataclass
class MainArticle:
    """The article a request builds on, and how it was found."""

    normalized: NormalizedTopic
    subjects: list[str]  # all of equal weight
    resolution: Resolution
    choice: ArticleChoiceReport | None = None  # the LLM deciding an unsure topic (D35)
    node: NodeArticleReport | None = None  # how a material's article was found (D47)
    material: str | None = None  # the material's own article beside the topic's, for the corpus
    articles: TopicArticlesReport | None = None  # the overview and the parts the LLM named for a topic (D63)


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
    found = derive_topic(topic, derived, subject, is_subject=catalog.knows)
    terms = catalog.context_terms_of(found.subjects)
    around = [word for entry in derived for word in entry.context]  # the words the node and the collection bring

    def by_rules(title: str) -> Resolution:
        normalized = normalize_topic(title, is_subject=catalog.knows)
        context = [*normalized.context, *around]
        return registry.resolve_topic(normalized.topic, context=context, query=found.normalized.query, terms=terms)

    def by_name(title: str) -> Resolution | None:
        """The article the model named, as the archive has it (D35): its title or a redirect, a disambiguation page
        decided by the subject. A name that only title suggestions or full-text hits reach counts as missing (M25)."""
        named = registry.resolve_topic(title, query=found.normalized.query)
        if named.method == "disambiguation":
            named = by_rules(title)
        return named if named.resolved and named.method not in GUESSED else None

    def as_found(
        resolution: Resolution,
        choice: ArticleChoiceReport | None = None,
        report: NodeArticleReport | None = None,
        material: str | None = None,
        articles: TopicArticlesReport | None = None,
    ) -> MainArticle:
        normalized = found.normalized
        if report is not None and not topic and resolution.resolved:  # the material's topic is the article found
            normalized = replace(normalized, topic=resolution.normalized)
        return MainArticle(normalized, found.subjects, resolution, choice, report, material, articles)

    def the_articles() -> TopicArticlesReport | None:
        """With a job, the question N for the request's topic (D63), which hears its subjects too."""
        leading = registry.primary_archive
        if job is None or leading is None:
            return None
        return ask_topic_articles(job, leading, found.normalized.topic, catalog.labels_of(found.subjects))

    def the_topic() -> tuple[Resolution, ArticleChoiceReport | None, TopicArticlesReport | None]:
        """The rules, and with a job the question N (D63) and the choice among the rules' candidates (D35).

        Where the rules missed the topic the first title N found replaces their article: the overview, or the first
        part when the archive lacks the overview, as measured (M37, M39)."""
        chooser = LlmArticleChooser(job, found.normalized.topic, catalog.labels_of(found.subjects)) if job else None
        articles = the_articles()
        overview = articles.found[0] if articles is not None and articles.found else None
        resolution = registry.resolve_topic(
            found.normalized.topic,
            context=found.context,
            query=found.normalized.query,
            terms=terms,
            chooser=chooser,
            thorough=job is not None and job.thorough,
            overview=overview,
        )
        if articles is not None and overview is not None:
            # the overview took the rules' place: where they missed the topic, or where the chooser rejected all (A01)
            chose = chooser is not None and chooser.report.offered > 0 and not chooser.report.rejected
            articles.main = resolution.title == overview and resolution.method == CHOSEN_BY_LLM and not chose
        return resolution, chooser.report if chooser is not None else None, articles

    if node is None or node.kind != "material":
        resolution, choice, articles = the_topic()
        return as_found(resolution, choice=choice, articles=articles)

    report = NodeArticleReport()
    answer = ask_topic(job, node, report, topic=topic) if job is not None else None
    if answer is not None:
        named, own = answer
        if not named and not topic:  # the model sees no subject topic in the material
            return as_found(_none(found), report=report)
        answered = by_name(named) if named else None
        if answered is not None:
            material = by_name(own) if own else None
            report.material = material.title if material is not None else None
            # A topic sent along gets its parts as well; the article stays the one this question named
            articles = the_articles() if topic else None
            return as_found(answered, report=report, material=report.material, articles=articles)
        if named:
            report.fallback = NAMED_TITLE_MISSING
    report.way = "rules"
    rules = _by_the_rules(registry, node, by_rules, report)
    if not topic:
        return as_found(rules or _none(found), report=report)
    resolution, choice, articles = the_topic()
    report.material = rules.title if rules is not None else None
    return as_found(resolution, choice, report, report.material, articles)


def _by_the_rules(
    registry: ZimRegistry, node: NodeInfo, by_rules: Callable[[str], Resolution], report: NodeArticleReport
) -> Resolution | None:
    """The article the rules find for a material (M23), or ``None``; the report gets the title's article and terms."""
    titled = by_rules(node.title)
    report.title_article = titled.title
    report.entities = ranked_entities(registry.archives, node.title, node.description, node.keywords)
    pick = rule_article(titled.title, report.entities, node.title)
    # resolved by its own title: the material's title may have reached it only through a search hit (a guess)
    return by_rules(pick) if pick is not None else None


def _none(found: DerivedTopic) -> Resolution:
    """No article: the resolution shows what came in and nothing else."""
    return Resolution(query=found.normalized.query, normalized=found.normalized.topic, context=list(found.context))
