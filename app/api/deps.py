"""Shared request dependencies for the v2 routers."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import HTTPException, Request

from app.domain.models import Resolution, Source
from app.knowledge.topic import normalize_topic
from app.service import CompendiumService
from app.sources.zim.registry import ZimRegistry
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
) -> tuple[str, Resolution, list[Source]]:
    """Resolve a topic and build its corpus; shared by /knowledge and /qa.

    Returns the normalised topic, its resolution and the articles. A topic the archives do not have is a 404
    carrying the resolution, so the caller sees the alternatives instead of an empty answer.
    """
    normalized = normalize_topic(topic)
    resolution = registry.resolve_topic(normalized.topic, context=normalized.context, query=normalized.query)
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
    return normalized.topic, resolution, list(sources)
