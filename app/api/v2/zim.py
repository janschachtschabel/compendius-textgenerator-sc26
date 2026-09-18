"""ZIM archive endpoints: public status, admin catalog, progress, sync request and delete (PLAN.md 4.1, 8.2).

The API process never downloads. ``POST /sync`` leaves a request file that the updater loop picks
up; ``DELETE`` only touches files that are neither active nor open in this process.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.admin import require_admin
from app.jobs.zim_sync import TRIGGER_FILE, read_status
from app.settings import Settings
from app.sources.zim.active import ActiveState, read_active
from app.sources.zim.downloader import PART_SUFFIX, validate_file_name

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/zim", tags=["zim"])
admin = APIRouter(prefix="/api/v2/zim", tags=["zim-admin"], dependencies=[Depends(require_admin)])


def _active(settings: Settings) -> ActiveState:
    try:
        return read_active(settings.zim_dir) or ActiveState(profile=settings.zim_profile)
    except ValueError as exc:
        log.error("%s", exc)
        return ActiveState(profile=settings.zim_profile)


@router.get("/status")
def zim_status(request: Request) -> dict[str, Any]:
    registry = request.app.state.registry
    settings: Settings = request.app.state.settings
    required: list[str] = request.app.state.required_ids
    return {
        "archives": registry.snapshot(),
        "required": required,
        "missing_required": registry.has_ids(required),
        "profile": settings.zim_profile,
        "active": _active(settings).model_dump(),
        "sync": read_status(settings.zim_dir),
    }


@admin.get("/catalog")
def zim_catalog(request: Request) -> list[dict[str, Any]]:
    """German archives offered by Kiwix, marked as subscribed and installed (live call, admin only)."""
    manifest = request.app.state.manifest
    subscribed = {s.id for s in manifest.subscriptions} if manifest is not None else set()
    installed = {a.id for a in request.app.state.registry.archives}
    try:
        entries = request.app.state.catalog.entries()
    except Exception as exc:  # remote system; report instead of a stack trace
        raise HTTPException(status_code=502, detail=f"Kiwix-Katalog nicht erreichbar: {exc}") from exc
    return [
        {
            **entry.model_dump(),
            "archive_id": entry.archive_id,
            "download_url": entry.download_url,
            "dump_date": entry.dump_date,
            "has_fulltext": entry.has_fulltext,
            "subscribed": entry.archive_id in subscribed,
            "installed": entry.archive_id in installed,
        }
        for entry in entries
    ]


@admin.get("/progress")
def zim_progress(request: Request) -> dict[str, Any]:
    """Last status the sync job wrote, including a running download."""
    return read_status(request.app.state.settings.zim_dir) or {"state": "unknown", "last_run": None, "download": None}


@admin.post("/sync", status_code=202)
def zim_sync_now(request: Request) -> dict[str, Any]:
    """Ask the updater for a run; it polls for the request file, this process downloads nothing."""
    zim_dir = Path(request.app.state.settings.zim_dir)
    zim_dir.mkdir(parents=True, exist_ok=True)
    (zim_dir / TRIGGER_FILE).write_text("requested via API\n", encoding="utf-8")
    return {
        "requested": True,
        "note": "Der Updater (compendium zim sync --loop) führt den Abgleich beim nächsten Poll aus.",
    }


@admin.delete("/{file_name}")
def zim_delete(file_name: str, request: Request) -> dict[str, Any]:
    """Delete a stray archive (and its .part file); active or open archives are refused."""
    settings: Settings = request.app.state.settings
    try:
        validate_file_name(file_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    in_use = {a.file for a in _active(settings).archives.values()}
    in_use |= {a.file_name for a in request.app.state.registry.archives}
    if file_name in in_use:
        raise HTTPException(status_code=409, detail="Datei ist aktiv; erst per Sync ablösen, dann löschen.")
    path = Path(settings.zim_dir) / file_name
    removed: list[str] = []
    for candidate in (path, path.with_name(path.name + PART_SUFFIX)):
        if candidate.exists():
            candidate.unlink()
            removed.append(candidate.name)
    if not removed:
        raise HTTPException(status_code=404, detail="Datei nicht vorhanden.")
    log.info("deleted %s", removed)
    return {"removed": removed}
