"""Knowledge texts for a topic, without a compendium (docs/umbau.md, U2).

The corpus of a compendium is useful on its own: a caller that wants the sources should not have to ask for a
whole compendium and throw the template away. This endpoint resolves the topic and hands back the articles the
corpus builder would use, with their sections, optionally limited to single archives.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_service
from app.api.limits import rate_limited
from app.domain.models import Resolution, Source
from app.knowledge.topic import normalize_topic
from app.service import CompendiumService
from app.sources.zim.registry import ZimRegistry
from app.templates.manager import TemplateNotFoundError

router = APIRouter(prefix="/api/v2", tags=["v2"])


class KnowledgeRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"topic": "Optik", "max_chars": 20000}]})

    topic: str = Field(min_length=1, max_length=300)
    archives: list[str] = Field(default_factory=list, description="Archive ids to ask; empty asks every active archive")
    max_articles: int | None = Field(
        None,
        ge=1,
        le=50,
        description="Bound of the extra articles (default CORPUS_MAX_ARTICLES); the topic and its twin in "
        "another archive are always included",
    )
    max_chars: int | None = Field(None, ge=100, description="Cap over all articles; cuts at section borders")
    template_id: str | None = Field(None, description="Its slots steer the full-text search for extra articles")


class KnowledgeSection(BaseModel):
    heading: str
    level: int
    text: str


class KnowledgeArticle(BaseModel):
    source_id: str
    archive: str = Field(description="Archive id, as in /api/v2/zim/status")
    project: str
    title: str
    url: str
    origin: str = Field(description="primary | same_topic | linked | search | lookup")
    is_primary: bool
    chars: int
    lead: str
    sections: list[KnowledgeSection]


class KnowledgeResponse(BaseModel):
    topic: str
    resolution: Resolution
    archives: list[str] = Field(description="The archives that were asked")
    articles: list[KnowledgeArticle]
    chars: int
    truncated: bool = Field(description="True when max_chars ended the answer early")


def _sections(source: Source) -> list[KnowledgeSection]:
    """Every section with text; the lead keeps its empty heading, as in the article."""
    sections = []
    for section in source.sections:
        text = "\n\n".join(paragraph.text for paragraph in section.paragraphs).strip()
        if text:
            sections.append(KnowledgeSection(heading=section.heading, level=section.level, text=text))
    return sections


def _article(source: Source, archive_id: str, sections: list[KnowledgeSection]) -> KnowledgeArticle:
    return KnowledgeArticle(
        source_id=source.source_id,
        archive=archive_id,
        project=source.project,
        title=source.title,
        url=source.url,
        origin=source.origin,
        is_primary=source.is_primary,
        chars=sum(len(section.text) for section in sections),
        lead=source.lead_text[:400],
        sections=sections,
    )


def _registry(service: CompendiumService, archive_ids: list[str]) -> ZimRegistry:
    """The registry, narrowed to the requested archives; an unknown id is a 404 rather than a silent miss."""
    registry = service.registry
    if not archive_ids:
        return registry
    unknown = [name for name in archive_ids if name not in {a.id for a in registry.archives}]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unbekannte Archive: {', '.join(unknown)}")
    return registry.only(archive_ids)


@router.post(
    "/knowledge",
    response_model=KnowledgeResponse,
    dependencies=[Depends(rate_limited)],
    summary="Wissenstexte zu einem Thema",
)
def knowledge(payload: KnowledgeRequest, request: Request) -> KnowledgeResponse:
    """Resolve the topic and return the articles of its corpus, with their sections."""
    service = get_service(request)
    registry = _registry(service, payload.archives)
    normalized = normalize_topic(payload.topic)
    resolution = registry.resolve_topic(normalized.topic, context=normalized.context, query=normalized.query)
    if not resolution.resolved:
        raise HTTPException(
            status_code=404,
            detail={"message": "Thema in den Archiven nicht gefunden", "resolution": resolution.model_dump()},
        )
    try:
        template = service.templates.get(payload.template_id or service.settings.template_default)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc

    sources = registry.build_corpus(
        resolution,
        slots=template.content_slots(),
        max_articles=payload.max_articles or service.settings.corpus_max_articles,
    )
    by_file = {archive.file_name: archive.id for archive in registry.archives}
    articles: list[KnowledgeArticle] = []
    total, truncated = 0, False
    for source in sources:
        kept: list[KnowledgeSection] = []
        for section in _sections(source):
            if payload.max_chars is not None and total + len(section.text) > payload.max_chars:
                truncated = True
                break
            kept.append(section)
            total += len(section.text)
        articles.append(_article(source, by_file.get(source.zim_file or "", ""), kept))
        if truncated:
            break
    return KnowledgeResponse(
        topic=normalized.topic,
        resolution=resolution,
        archives=[archive.id for archive in registry.archives],
        articles=articles,
        chars=total,
        truncated=truncated,
    )
