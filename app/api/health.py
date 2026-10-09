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
from pydantic import BaseModel, Field

from app import __version__, revision
from app.api.system_threads import run_system
from app.sources.gnd.index import GndIndex
from app.sources.wikidata.index import WikidataIndex

router = APIRouter(tags=["system"])


def _host(url: str) -> str:
    """Only the host of a configured address; the path adds nothing a reader of /health needs."""
    return urlparse(url).hostname or ""


def _wikidata(index: WikidataIndex) -> dict[str, Any]:
    """The Wikidata index as it is now, not as at start: the sync builds or replaces it while the service runs
    (D64); without it the linked articles carry no Wikidata number (D43)."""
    meta = index.meta()
    return {"available": index.available, "articles": meta.get("articles"), "dump": meta.get("dump")}


def _gnd(index: GndIndex | None) -> dict[str, Any]:
    """The GND index as it is now (D65); without it an article lacking a Normdaten block has no GND."""
    meta = index.meta() if index is not None else {}
    available = index is not None and index.available
    return {"available": available, "records": meta.get("records"), "release": meta.get("release")}


def _components(request: Request) -> dict[str, Any]:
    registry = request.app.state.registry
    settings = request.app.state.settings
    missing = registry.has_ids(request.app.state.required_ids)
    llm = getattr(request.app.state, "llm", None)
    llm_status: dict[str, Any] = (
        llm.status()
        if llm is not None
        else {
            "enabled": False,
            "provider": settings.b_api_provider,
            "model": settings.b_api_model,
            "route": settings.b_api_route_name or None,
            "available": False,
        }
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
        "entities": {
            **request.app.state.entities,
            "wikidata": _wikidata(request.app.state.wikidata),
            "gnd": _gnd(getattr(request.app.state, "gnd", None)),
        },
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
    """The process lives: version, timestamp and the state of the archives, the curriculum cache,
    edu-sharing and the LLM. Always 200 - for the question whether the service can work, ask /ready.
    """
    components = await run_system(request, _components, request)
    return {
        "status": "healthy",
        "service": "compendious-text-fastapi",
        "version": __version__,
        "revision": revision(),
        "timestamp": datetime.now(UTC).isoformat(),
        "components": components,
    }


class Readiness(BaseModel):
    """The answer of /ready, alike for 200 and 503."""

    ready: bool = Field(description="Whether the archives are loaded and none of the required ones is missing")
    components: dict[str, Any] = Field(description="The components as /health names them: a failing probe says why")


@router.get(
    "/ready",
    response_model=Readiness,
    # the 503 was the answer OpenAPI did not name (audit 2026-09-28, AP-05)
    responses={503: {"model": Readiness, "description": "Not ready: archives still loading or a required one missing"}},
)
async def ready(request: Request) -> JSONResponse:
    """Whether the service can work: 200 when the archives are loaded and none of the required ones is
    missing, 503 otherwise. The same components as /health come along, so a probe that fails says why.
    """
    components = await run_system(request, _components, request)
    is_ready = request.app.state.registry.ready and not components["zim"]["missing_required"]
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"ready": is_ready, "components": components},
    )
