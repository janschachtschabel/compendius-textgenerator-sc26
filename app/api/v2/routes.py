"""v2 endpoints: compendium generation and templates (archives: zim.py, matching: matching.py).

Reading templates is open; writing and deleting them sit behind ``ADMIN_TOKEN`` like the archive
endpoints, because a template decides what every following compendium looks like (docs/umbau.md U6).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.admin import require_admin
from app.api.deps import get_service
from app.api.limits import rate_limited
from app.domain.models import Compendium
from app.domain.requests import GenerateRequest
from app.matching.registry import UnknownMatcherError
from app.observability.metrics import record_compendium
from app.service import PartsUnavailableError, TopicNotFoundError
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError
from app.templates.manager import TemplateNotFoundError
from app.templates.schema import Template

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["v2"])
admin = APIRouter(prefix="/api/v2", tags=["v2-admin"], dependencies=[Depends(require_admin)])


EXAMPLES = {
    "kuerzeste Anfrage": {
        "summary": "Das Nötigste: ein Thema, zwei Teile, eine Ziellänge",
        "value": {"topic": "Optik", "parts": ["world", "curricula"], "target_length": 8000},
    },
    "mit den Schaltern": {
        "summary": "Was sonst noch geht: Template, Matching, die drei KI-Schalter, Facetten",
        "description": (
            "extraction wählt die Sätze, generation formuliert die Bausteine, enrichment entscheidet, ob das "
            "Modell eigenes Wissen beisteuern darf. Alle drei fallen auf rule-based zurück, wenn die b-api "
            "fehlt, und audit sagt hinterher, was wirklich lief."
        ),
        "value": {
            "topic": "Optik",
            "parts": ["world", "curricula"],
            "target_length": 12000,
            "template_id": "sc26",
            "matcher": "hybrid_light",
            "extraction": "llm",
            "generation": "llm-fast",
            "enrichment": "sources-only",
            "facets_visible": True,
            "max_articles": 12,
            "empty_slot_policy": "note",
        },
    },
}


@router.post(
    "/compendium",
    response_model=Compendium,
    dependencies=[Depends(rate_limited)],
    summary="Kompendium erzeugen",
)
def generate_compendium(
    payload: Annotated[GenerateRequest, Body(openapi_examples=EXAMPLES)], request: Request
) -> Compendium:
    """Generate the compendium for a topic or a collection: the requested parts, with the requested switches.

    **What it makes.** ``parts`` picks the parts: ``world`` is part 1, the compendium text itself;
    ``curricula`` is part 2, the curriculum elements; ``collection`` is part 3, the materials of an
    edu-sharing collection and needs ``collection_id``. Without ``world`` there is no part 1, no sources
    of its own, no matching and no knowledge collection - the rest is rule-based by definition.

    **How long it gets.** ``target_length`` is shared over the blocks by weight and steers upwards until
    the sources run out. It is a steer, not a cap: a block is never shorter than its first paragraph.

    **Who writes it.** Three switches, and each falls back to ``rule-based`` when the b-api is missing:
    ``extraction`` picks the sentences (``rule-based`` takes the policy's paragraphs, ``llm`` lets the
    model choose among the best candidates and the wording stays the source's), ``generation`` writes the
    blocks (``rule-based``, ``llm-fast`` for the main ones, ``llm`` for every one - every sentence cited),
    and ``enrichment`` decides whether the model may add knowledge of its own (``sources-only`` or
    ``model-knowledge``, which is marked in the text). ``audit`` says afterwards what really ran.

    **What else.** ``matcher`` picks the strategy (unknown: 422), ``template_id`` the template,
    ``max_articles`` the size of the corpus, ``facets_visible`` and ``empty_slot_policy`` override the
    settings and the template. ``existing_markdown`` with ``regenerate_sections`` makes only the named
    blocks anew and keeps the rest word for word.

    **When it refuses.** Topic not in the archives: 404 with the resolution and its alternatives. Unknown
    collection: 404. Repository unreachable: 502. No requested part can be made at all - part 3 without
    ``EDU_SHARING_BASE_URL``, for instance: 503.
    """
    service = get_service(request)
    try:
        compendium = service.generate(payload)
    except TopicNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": "Thema in den Archiven nicht gefunden", "resolution": exc.resolution.model_dump()},
        ) from exc
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc  # the messages name the repository
    except EduSharingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc
    except UnknownMatcherError as exc:
        raise HTTPException(status_code=422, detail=f"Unbekannte Matching-Strategie: {exc}") from exc
    except PartsUnavailableError as exc:
        # A gap in the configuration that no retry fixes; the log keeps it apart from missing archives
        log.warning("compendium request refused: %s", exc)
        raise HTTPException(status_code=503, detail=f"Kein angefragter Teil ist erzeugbar: {exc}") from exc
    record_compendium(compendium)
    return compendium


@router.get("/templates")
def list_templates(request: Request) -> list[dict[str, Any]]:
    """The templates this service knows, built-in and custom, with their slot count and version.

    A short row each: id, version, name, description, how many blocks it has and whether it ships with
    the image. The blocks themselves are in ``GET /api/v2/templates/{id}``. The id goes into
    ``template_id`` of a compendium request; without one the default from the settings applies.
    """
    return [
        {
            "id": t.id,
            "version": t.version,
            "name": t.name,
            "description": t.description,
            "slots": len(t.slots),
            "builtin": t.builtin,
        }
        for t in request.app.state.templates.list()
    ]


@router.get("/templates/{template_id}")
def get_template(template_id: str, request: Request) -> dict[str, Any]:
    """One template in full: every block with its budget, facets, search queries and generator.

    This is the shape ``PUT /api/v2/templates/{id}`` takes back, so it is also the way to start a custom
    template - read a built-in one, change what you need, write it under your own id. An unknown id is a
    404.
    """
    try:
        template = request.app.state.templates.get(template_id)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {template_id}") from exc
    data: dict[str, Any] = template.model_dump()
    return data


@admin.put("/templates/{template_id}", summary="Template anlegen oder ersetzen")
def put_template(template_id: str, payload: Template, request: Request) -> dict[str, Any]:
    """Store a custom template under this id; the version counts up on every write.

    The id in the path and the id in the body have to agree: silently renaming what the caller sent would
    put a template somewhere they did not ask for. Built-in templates are read-only (409).
    """
    if payload.id != template_id:
        raise HTTPException(
            status_code=422, detail=f"id im Pfad ({template_id}) und im Body ({payload.id}) stimmen nicht überein"
        )
    try:
        stored = request.app.state.templates.save(payload)
    except ValueError as exc:  # a built-in id; the message names it and says what to do instead
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log.info("template %s saved as version %d", stored.id, stored.version)
    data: dict[str, Any] = stored.model_dump()
    return data


@admin.delete("/templates/{template_id}", status_code=204, summary="Template löschen")
def delete_template(template_id: str, request: Request) -> None:
    """Delete a custom template (204).

    Built-in templates ship with the image and are refused (409); an unknown id is a 404. A compendium
    request naming the deleted id answers 404 from then on, so check what still uses it first.
    """
    try:
        removed = request.app.state.templates.delete(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {template_id}")
    log.info("template %s deleted", template_id)
