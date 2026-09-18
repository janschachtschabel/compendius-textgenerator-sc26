"""Shared request dependencies for the v2 routers."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.service import CompendiumService


def get_service(request: Request) -> CompendiumService:
    """The compendium service, or 503 while no archive is loaded."""
    service: CompendiumService | None = request.app.state.service
    if service is None or not request.app.state.registry.ready:
        raise HTTPException(status_code=503, detail="Keine ZIM-Archive geladen; Dienst nicht bereit.")
    return service
