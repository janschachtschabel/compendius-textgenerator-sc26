"""Shared request dependencies for the v2 routers."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError

from app.domain.caller_values import listed
from app.service import CompendiumService
from app.sources.zim.registry import ZimRegistry


def get_service(request: Request) -> CompendiumService:
    """The compendium service, or 503 while no archive is loaded."""
    service: CompendiumService | None = request.app.state.service
    if service is None or not request.app.state.registry.ready:
        raise HTTPException(status_code=503, detail="Keine ZIM-Archive geladen; Dienst nicht bereit.")
    return service


def no_unknown_query(request: Request) -> None:
    """A query parameter the route does not take is a 422 that names it, as an unknown field of a body is: a typo such
    as ``prest=best-quality`` ran the server's profile - maybe not the one meant, maybe with LLM costs - and the answer
    looked right (audit 2026-09-29, S10). The route's own parameters are the ones it declares."""
    dependant = getattr(request.scope.get("route"), "dependant", None)
    known = [param.alias for param in getattr(dependant, "query_params", ())]
    unknown = [name for name in request.query_params if name not in known]
    if unknown:
        takes = f"; bekannt sind {', '.join(known)}" if known else ""
        raise RequestValidationError(
            [
                {"type": "extra_forbidden", "loc": ("query", name), "msg": f"Unbekannter Parameter{takes}"}
                for name in unknown
            ]
        )


def archives_for(registry: ZimRegistry, archive_ids: Sequence[str]) -> ZimRegistry:
    """The registry narrowed to the named archives; an unknown id is a 404 rather than a silent miss."""
    if not archive_ids:
        return registry
    known = {archive.id for archive in registry.archives}
    unknown = [name for name in archive_ids if name not in known]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unbekannte Archive: {listed(unknown)}")
    return registry.only(archive_ids)
