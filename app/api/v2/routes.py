"""v2 endpoints: compendium generation and templates (archives: zim.py, matching: matching.py)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_service
from app.api.limits import rate_limited
from app.domain.models import Compendium
from app.domain.requests import GenerateRequest
from app.matching.registry import UnknownMatcherError
from app.observability.metrics import record_compendium
from app.service import PartsUnavailableError, TopicNotFoundError
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError
from app.templates.manager import TemplateNotFoundError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["v2"])


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
