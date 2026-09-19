"""Legacy linker (PLAN.md 8.1, D14): the entities come from the archives, not from an LLM.

The old endpoint asked a model for entities and looked them up in the Wikipedia API. The new one resolves the
text as a topic and answers with the articles the compendium would use: the article itself (``extract``) and,
for ``MODE=generate``, its neighbours from links and search. The answer keeps the old shape; fields the
archives cannot fill (Wikidata id, categories, thumbnails, coordinates) stay empty, and the id of an entity is
the stable article id instead of a fresh UUID per request.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_service
from app.api.limits import rate_limited
from app.api.v1.models import (
    EntityDetails,
    LinkerEndpointConfig,
    LinkerEntity,
    LinkerEntitySources,
    LinkerRequest,
    LinkerResponse,
    LinkerStatistics,
    LinkerWikipediaSource,
)
from app.domain.models import Source
from app.domain.requests import GenerateRequest
from app.service import TopicNotFoundError

router = APIRouter(prefix="/api/v1", tags=["v1"])

MAX_ARTICLES = 50  # the request model of the new service allows no more
NAMED_ORIGINS = {"primary", "same_topic"}  # what the text itself names; the rest are the generated neighbours
PRIMARY_TYPE, RELATED_TYPE = "TOPIC", "RELATED"


@router.post("/linker", response_model=LinkerResponse, dependencies=[Depends(rate_limited)])
def linker(payload: LinkerRequest, request: Request) -> LinkerResponse:
    """Entities of a text: the resolved article and, with ``MODE=generate``, the articles around it."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    config = payload.config if payload.config is not None else LinkerEndpointConfig(MODE="generate")
    limit = min(config.MAX_ENTITIES, MAX_ARTICLES)
    service = get_service(request)
    try:
        prepared = service.prepare(GenerateRequest(topic=text, parts=["world"], max_articles=limit))
        sources = prepared.sources
    except TopicNotFoundError:  # nothing found is an answer, not a failure
        sources = []
    if config.MODE == "extract":
        sources = [source for source in sources if source.origin in NAMED_ORIGINS]
    entities = [_entity(source) for source in sources[:limit]]
    return LinkerResponse(original_text=text, entities=entities, statistics=_statistics(entities, sources[:limit]))


def _entity(source: Source) -> LinkerEntity:
    return LinkerEntity(
        entity=source.title,
        details=EntityDetails(
            typ=PRIMARY_TYPE if source.origin in NAMED_ORIGINS else RELATED_TYPE, citation=source.title
        ),
        sources=LinkerEntitySources(
            wikipedia=LinkerWikipediaSource(
                status="found",
                label_de=source.title,
                url_de=source.url,
                extract=source.lead_text[:400] or None,
                internal_links=list(source.relation_titles),
            )
        ),
        id=source.source_id,
    )


def _statistics(entities: list[LinkerEntity], sources: list[Source]) -> LinkerStatistics:
    total = len(entities)
    links = Counter(title for source in sources for title in source.relation_titles)
    return LinkerStatistics(
        total_entities=total,
        top10={"wikipedia_categories": {}, "wikipedia_internal_links": dict(links.most_common(10))},
        types_distribution=dict(Counter(entity.details.typ for entity in entities)),
        linked={
            "wikipedia": {"count": total, "percent": 100.0 if total else 0},
            "wikidata": {"count": 0, "percent": 0},  # the archives carry no Wikidata ids
        },
    )
