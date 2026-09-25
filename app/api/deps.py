"""Shared request dependencies for the v2 routers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException, Request

from app.domain.models import Resolution, Source
from app.knowledge.article_choice import CHECKED_ORIGINS, LlmArticleChooser, check_hits, choice_block, choice_used
from app.llm.deadline import Deadline
from app.service import CompendiumService, RepositoryUnavailableError
from app.sources.wlo.client import EduSharingError, NodeNotFoundError
from app.sources.wlo.part import CollectionTopic, derive_topic
from app.sources.wlo.repository import RepositoryNotAllowedError
from app.sources.zim.registry import CHOSEN_BY_LLM, ZimRegistry
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
) -> tuple[str, Resolution, list[Source], dict[str, Any] | None]:
    """Resolve a topic and build its corpus for /knowledge, with the article choice a compendium makes (D35, D40).

    Returns the normalised topic, its resolution, the articles and what the article choice asked and decided - None
    when the rules chose alone. A topic the archives do not have is a 404 carrying the resolution, so the caller sees
    the alternatives instead of an empty answer.
    """
    found = derive_topic(topic, derived)  # as a compendium derives it: a topic sent along wins over the node
    normalized, subjects = found.normalized, found.subjects
    requested, note, job = service.article_choice_job(article_choice, Deadline(service.settings.request_timeout_s))
    labels = service.subjects.labels_of(subjects)
    chooser = LlmArticleChooser(job, normalized.topic, labels) if job is not None else None
    resolution = registry.resolve_topic(
        normalized.topic,
        context=found.context,
        query=normalized.query,
        terms=service.subjects.context_terms_of(subjects),
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
    side_articles = sum(1 for source in sources if source.origin in CHECKED_ORIGINS)
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
        not resolution.confident or side_articles > 0,
        choice,
        resolution.title if chosen else None,
        hit_check,
    )
    info["tokens"] = sum(report.total_tokens for report in (choice, hit_check) if report is not None)
    info["note"] = note
    return normalized.topic, resolution, list(sources), info
