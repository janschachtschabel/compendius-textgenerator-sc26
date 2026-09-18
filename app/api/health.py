"""Health (process alive) and readiness (archives present)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import __version__

router = APIRouter(tags=["system"])


def _components(request: Request) -> dict[str, Any]:
    registry = request.app.state.registry
    settings = request.app.state.settings
    missing = registry.has_ids(request.app.state.required_ids)
    llm = getattr(request.app.state, "llm", None)
    llm_status: dict[str, Any] = (
        llm.status()
        if llm is not None
        else {"enabled": False, "provider": settings.b_api_provider, "model": settings.b_api_model, "available": False}
    )
    return {"zim": {"archives": registry.snapshot(), "missing_required": missing}, "llm": llm_status}


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "compendious-text-fastapi",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
        "components": _components(request),
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    components = _components(request)
    is_ready = request.app.state.registry.ready and not components["zim"]["missing_required"]
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"ready": is_ready, "components": components},
    )
