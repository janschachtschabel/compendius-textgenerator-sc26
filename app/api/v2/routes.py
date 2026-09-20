"""v2 endpoints: compendium generation and templates (archives: zim.py, matching: matching.py).

Reading templates is open; writing and deleting them sit behind ``ADMIN_TOKEN`` like the archive
endpoints, because a template decides what every following compendium looks like (docs/umbau.md U6).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

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


@router.post(
    "/compendium",
    response_model=Compendium,
    dependencies=[Depends(rate_limited)],
    summary="Kompendium erzeugen",
)
def generate_compendium(payload: GenerateRequest, request: Request) -> Compendium:
    """Generate the compendium for a topic or a collection: the requested parts, with the requested switches."""
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
    """Delete a custom template; built-in templates are refused (409), an unknown id is a 404."""
    try:
        removed = request.app.state.templates.delete(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {template_id}")
    log.info("template %s deleted", template_id)
