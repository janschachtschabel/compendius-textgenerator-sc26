"""Shared request dependencies for the v2 routers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, Request

from app.domain.models import Resolution, Source
from app.knowledge.article_choice import CHECKED_ORIGINS, check_hits, choice_block, choice_used
from app.knowledge.main_article import choose_main_article
from app.knowledge.node_article import node_block
from app.knowledge.topic_articles import settle
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.service import CompendiumService, TopicNotFoundError
from app.sources.wlo.models import NodeInfo
from app.sources.wlo.part import CollectionTopic
from app.sources.zim.registry import CHOSEN_BY_LLM, NODE_ORIGIN, ZimRegistry


def get_service(request: Request) -> CompendiumService:
    """The compendium service, or 503 while no archive is loaded."""
    service: CompendiumService | None = request.app.state.service
    if service is None or not request.app.state.registry.ready:
        raise HTTPException(status_code=503, detail="Keine ZIM-Archive geladen; Dienst nicht bereit.")
    return service


def archives_for(registry: ZimRegistry, archive_ids: Sequence[str]) -> ZimRegistry:
    """The registry narrowed to the named archives; an unknown id is a 404 rather than a silent miss."""
    if not archive_ids:
        return registry
    unknown = [name for name in archive_ids if name not in {archive.id for archive in registry.archives}]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unbekannte Archive: {', '.join(unknown)}")
    return registry.only(archive_ids)


def corpus_for_topic(
    service: CompendiumService,
    registry: ZimRegistry,
    topic: str | None,
    *,
    template_id: str | None = None,
    max_articles: int | None = None,
    article_choice: str | None = None,
    derived: Sequence[CollectionTopic] = (),
    node: NodeInfo | None = None,
    subject: str | None = None,
    budget: RequestBudget | None = None,
) -> tuple[str, Resolution, list[Source], dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve a topic and build its corpus for /knowledge, with the article choice a compendium makes (D35, D40, D47).

    ``budget`` is the request's, the size of its profile (D59).

    Returns the normalised topic, its resolution, the articles, what the article choice asked and decided - None
    when the rules chose alone - and how the article of a material node was found (None without one). A topic the
    archives do not have is a 404 carrying the resolution, so the caller sees the alternatives instead of an empty
    answer; a material the rules find no article for says to send a topic.
    """
    # before the article choice, which may ask the LLM
    template = service.templates.get(template_id or service.settings.template_default)
    deadline = Deadline(service.settings.request_timeout_s)
    requested, note, job = service.article_choice_job(article_choice, deadline, budget)
    chosen = choose_main_article(registry, service.subjects, topic, derived, subject=subject, node=node, job=job)
    resolution, normalized = chosen.resolution, chosen.normalized
    if not resolution.resolved:
        raise TopicNotFoundError(resolution, chosen.node, from_material=not topic)
    sources = registry.build_corpus(
        resolution,
        slots=template.content_slots(),
        max_articles=max_articles or service.settings.corpus_max_articles,
        material=chosen.material,
        named=chosen.articles.found if chosen.articles is not None else (),
    )
    if chosen.articles is not None:
        settle(chosen.articles, sources)
    if chosen.node is not None:
        chosen.node.added = any(source.origin == NODE_ORIGIN for source in sources)
    side_articles = sum(1 for source in sources if source.origin in CHECKED_ORIGINS)
    hit_check = None
    if job is not None:
        gone, hit_check = check_hits(job, resolution.title or normalized.topic, sources)
        sources = [source for source in sources if source.source_id not in gone]
    node_info = node_block(chosen.node) if chosen.node is not None else None
    if requested == "rule-based":
        return normalized.topic, resolution, list(sources), None, node_info
    by_llm = resolution.method == CHOSEN_BY_LLM
    named = chosen.node is not None and chosen.node.way == "llm"
    articles = chosen.articles
    info = choice_block(
        requested,
        choice_used(by_llm or named, hit_check, articles),
        not resolution.confident or side_articles > 0 or chosen.node is not None or articles is not None,
        chosen.choice,
        resolution.title if by_llm else None,
        hit_check,
        articles,
    )
    reports = (chosen.choice, hit_check, chosen.node, articles)
    info["tokens"] = sum(report.total_tokens for report in reports if report is not None)
    info["note"] = note
    return normalized.topic, resolution, list(sources), info, node_info
