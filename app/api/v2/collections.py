"""Collection endpoint (PLAN.md 8.2): part 3 for one collection, read from the edu-sharing repository."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.limits import rate_limited
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError, validate_node_id
from app.sources.wlo.part import CollectionBuilder

router = APIRouter(prefix="/api/v2/collections", tags=["collections"])


@router.get("/{collection_id}/overview", dependencies=[Depends(rate_limited)])
def collection_overview(collection_id: str, request: Request) -> dict[str, Any]:
    """Purpose, key figures and compact material lists of a collection (cached for an hour)."""
    builder: CollectionBuilder | None = request.app.state.collections
    if builder is None:
        raise HTTPException(status_code=503, detail="Kein edu-sharing-Repository konfiguriert (EDU_SHARING_BASE_URL).")
    try:
        validate_node_id(collection_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        part = builder.overview(collection_id)
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EduSharingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc  # the message names the repository
    return part.model_dump()
