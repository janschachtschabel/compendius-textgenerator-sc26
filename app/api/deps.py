"""Shared request dependencies for the v2 routers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException, Request

from app.domain.models import Resolution, Source
from app.knowledge.article_choice import CHECKED_ORIGINS, check_hits, choice_block, choice_used
from app.knowledge.main_article import choose_main_article
from app.knowledge.node_article import node_block
from app.llm.deadline import Deadline
from app.service import CompendiumService, RepositoryUnavailableError, TopicNotFoundError
from app.sources.wlo.client import EduSharingError, NodeNotFoundError
from app.sources.wlo.models import NodeInfo
from app.sources.wlo.part import CollectionTopic
from app.sources.wlo.repository import RepositoryNotAllowedError
from app.sources.zim.registry import CHOSEN_BY_LLM, NODE_ORIGIN, ZimRegistry
from app.templates.manager import TemplateNotFoundError


def get_service(request: Request) -> CompendiumService:
    """The compendium service, or 503 while no archive is loaded."""
    service: CompendiumService | None = request.app.state.service
    if service is None or not request.app.state.registry.ready:
        raise HTTPException(status_code=503, detail="Keine ZIM-Archive geladen; Dienst nicht bereit.")
    return service


@contextmanager
def node_errors() -> Iterator[None]:
    """The answers when a node cannot be read (D45): an address outside the allowlist is a 422, an unknown node a
    404, a failing repository a 502 and none at all a 503. The messages name the repository."""
    try:
        yield
    except RepositoryNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepositoryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EduSharingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
) -> tuple[str, Resolution, list[Source], dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve a topic and build its corpus for /knowledge, with the article choice a compendium makes (D35, D40, D47).

    Returns the normalised topic, its resolution, the articles, what the article choice asked and decided - None
    when the rules chose alone - and how the article of a material node was found (None without one). A topic the
    archives do not have is a 404 carrying the resolution, so the caller sees the alternatives instead of an empty
    answer; a material the rules find no article for says to send a topic.
    """
    requested, note, job = service.article_choice_job(article_choice, Deadline(service.settings.request_timeout_s))
    chosen = choose_main_article(registry, service.subjects, topic, derived, node=node, job=job)
    resolution, normalized = chosen.resolution, chosen.normalized
    if not resolution.resolved:
        missing = TopicNotFoundError(resolution, chosen.node, from_material=not topic)
        raise HTTPException(status_code=404, detail=missing.detail())
    try:
        template = service.templates.get(template_id or service.settings.template_default)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc
    sources = registry.build_corpus(
        resolution,
        slots=template.content_slots(),
        max_articles=max_articles or service.settings.corpus_max_articles,
        material=chosen.material,
    )
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
    info = choice_block(
        requested,
        choice_used(by_llm or named, hit_check),
        not resolution.confident or side_articles > 0 or chosen.node is not None,
        chosen.choice,
        resolution.title if by_llm else None,
        hit_check,
    )
    reports = (chosen.choice, hit_check, chosen.node)
    info["tokens"] = sum(report.total_tokens for report in reports if report is not None)
    info["note"] = note
    return normalized.topic, resolution, list(sources), info, node_info
