"""Health (process alive) and readiness (archives present).

Both probes read SQLite (token budget, curriculum cache), so the reads run in the monitoring threads
(app/api/system_threads.py): a slow volume cannot stall the event loop, and compendium requests that hold the
default threads cannot hold up a probe. Neither probe calls a remote system.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.system_threads import run_system

router = APIRouter(tags=["system"])


def _host(url: str) -> str:
    """Only the host of a configured address; the path adds nothing a reader of /health needs."""
    return urlparse(url).hostname or ""


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
    llm_status = {**llm_status, "host": _host(settings.b_api_url)}
    curricula = getattr(request.app.state, "curricula", None)
    meta = curricula.store.meta() if curricula is not None else {}
    return {
        "zim": {"archives": registry.snapshot(), "missing_required": missing},
        "lehrplan_cache": {
            "available": curricula is not None and curricula.store.available,
            "harvested_at": meta.get("harvested_at"),
        },
        "matching": request.app.state.matching,
        "edu_sharing": {
            "enabled": getattr(request.app.state, "collections", None) is not None,
            # Which repository the collections come from, and which b-api belongs to it: an operator has to be
            # able to see whether this service is talking to staging or to production
            "repository": _host(settings.edu_sharing_base_url),
        },
        "llm": llm_status,
    }


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    components = await run_system(request, _components, request)
    return {
        "status": "healthy",
        "service": "compendious-text-fastapi",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
        "components": components,
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    components = await run_system(request, _components, request)
    is_ready = request.app.state.registry.ready and not components["zim"]["missing_required"]
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"ready": is_ready, "components": components},
    )
