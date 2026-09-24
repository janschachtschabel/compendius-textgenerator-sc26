"""Shared request dependencies for the v2 routers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, Request

from app.domain.models import Resolution, Source
from app.knowledge.article_choice import HIT_ORIGIN, LlmArticleChooser, check_hits, choice_block, choice_used
from app.knowledge.topic import normalize_topic
from app.llm.deadline import Deadline
from app.service import CompendiumService
from app.sources.zim.registry import CHOSEN_BY_LLM, ZimRegistry
from app.templates.manager import TemplateNotFoundError


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
    topic: str,
    *,
    template_id: str | None = None,
    max_articles: int | None = None,
    article_choice: str | None = None,
) -> tuple[str, Resolution, list[Source], dict[str, Any] | None]:
    """Resolve a topic and build its corpus for /knowledge, with the article choice a compendium makes (D35, D40).

    Returns the normalised topic, its resolution, the articles and what the article choice asked and decided - None
    when the rules chose alone. A topic the archives do not have is a 404 carrying the resolution, so the caller sees
    the alternatives instead of an empty answer.
    """
    normalized = normalize_topic(topic)
    requested, note, job = service.article_choice_job(article_choice, Deadline(service.settings.request_timeout_s))
    chooser = LlmArticleChooser(job, normalized.topic, normalized.subject) if job is not None else None
    resolution = registry.resolve_topic(
        normalized.topic,
        context=normalized.context,
        query=normalized.query,
        terms=service.subjects.context_terms(normalized.subject),
        chooser=chooser,
    )
    if not resolution.resolved:
        raise HTTPException(
            status_code=404,
            detail={"message": "Thema in den Archiven nicht gefunden", "resolution": resolution.model_dump()},
        )
    try:
        template = service.templates.get(template_id or service.settings.template_default)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc
    sources = registry.build_corpus(
        resolution,
        slots=template.content_slots(),
        max_articles=max_articles or service.settings.corpus_max_articles,
    )
    search_hits = sum(1 for source in sources if source.origin == HIT_ORIGIN)
    hit_check = None
    if job is not None:
        gone, hit_check = check_hits(job, resolution.title or normalized.topic, sources)
        sources = [source for source in sources if source.source_id not in gone]
    if requested == "rule-based":
        return normalized.topic, resolution, list(sources), None
    chosen = resolution.method == CHOSEN_BY_LLM
    choice = chooser.report if chooser is not None else None
    info = choice_block(
        requested,
        choice_used(chosen, hit_check),
        not resolution.confident or search_hits > 0,
        choice,
        resolution.title if chosen else None,
        hit_check,
    )
    info["tokens"] = sum(report.total_tokens for report in (choice, hit_check) if report is not None)
    info["note"] = note
    return normalized.topic, resolution, list(sources), info
