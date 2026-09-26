"""ZIM archive endpoints: public status, admin catalog, progress, sync request and delete (PLAN.md 4.1, 8.2).

The API process never downloads. ``POST /sync`` leaves a request file that the updater loop picks
up; ``DELETE`` only touches files that are neither active nor open in this process.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Path as PathParameter  # pathlib.Path is taken

from app.api.admin import require_admin
from app.jobs.zim_sync import TRIGGER_FILE, read_status
from app.settings import Settings
from app.sources.zim.active import ActiveState, read_active
from app.sources.zim.downloader import PART_SUFFIX, validate_file_name

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/zim", tags=["zim"])
PUBLIC_RUN_FIELDS = ("profile", "started_at", "finished_at", "adopted", "downloaded", "skipped", "missing", "pruned")
admin = APIRouter(prefix="/api/v2/zim", tags=["zim-admin"], dependencies=[Depends(require_admin)])


def _active(settings: Settings) -> ActiveState:
    try:
        return read_active(settings.zim_dir) or ActiveState(profile=settings.zim_profile)
    except ValueError as exc:
        log.error("%s", exc)
        return ActiveState(profile=settings.zim_profile)


def _public_sync(status: dict[str, Any] | None) -> dict[str, Any] | None:
    """The sync status without its error texts, which can name server paths; GET /progress (admin) keeps them."""
    if status is None:
        return None
    run = status.get("last_run")
    public_run: dict[str, Any] | None = None
    if isinstance(run, dict):
        errors = run.get("errors")
        public_run = {key: run.get(key) for key in PUBLIC_RUN_FIELDS}
        public_run["error_count"] = len(errors) if isinstance(errors, list) else 0
    return {
        "state": status.get("state"),
        "updated_at": status.get("updated_at"),
        "last_run": public_run,
        "download": status.get("download"),
    }


@router.get("/status")
def zim_status(request: Request) -> dict[str, Any]:
    """The archives: what is loaded, which ids are required and missing, the profile, the active set
    and the last sync (its error count; the texts are in GET /api/v2/zim/progress).
    """
    registry = request.app.state.registry
    settings: Settings = request.app.state.settings
    required: list[str] = request.app.state.required_ids
    return {
        "archives": registry.snapshot(),
        "required": required,
        "missing_required": registry.has_ids(required),
        "profile": settings.zim_profile,
        "active": _active(settings).model_dump(),
        "sync": _public_sync(read_status(settings.zim_dir)),
    }


@admin.get("/catalog")
def zim_catalog(request: Request) -> list[dict[str, Any]]:
    """The German archives Kiwix offers, each marked as subscribed and installed.

    A live call to the Kiwix catalogue, so it needs the network and takes as long as that takes. What is
    already here is marked, so the list shows at a glance what a sync would fetch. ``ZIM_CATALOG_URL``
    points it elsewhere. Admin only.
    """
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
    """Where the sync job stands, including a download in flight and the error texts.

    The counterpart of ``GET /api/v2/zim/status``, which keeps the texts out because they can name server
    paths - here they are, which is why this one is admin only. A download in flight comes with its file
    and how far it got.
    """
    return read_status(request.app.state.settings.zim_dir) or {"state": "unknown", "last_run": None, "download": None}


@admin.post("/sync", status_code=202)
def zim_sync_now(request: Request) -> dict[str, Any]:
    """Ask the updater sidecar for a sync run.

    This process downloads nothing: it writes a request file that the updater polls. The answer says the
    request was placed, not that anything was fetched - ``GET /api/v2/zim/progress`` shows what came of
    it. Admin only.
    """
    zim_dir = Path(request.app.state.settings.zim_dir)
    zim_dir.mkdir(parents=True, exist_ok=True)
    (zim_dir / TRIGGER_FILE).write_text("requested via API\n", encoding="utf-8")
    return {
        "requested": True,
        "note": "Der Updater (compendium zim sync --loop) führt den Abgleich beim nächsten Poll aus.",
    }


@admin.delete("/{file_name}")
def zim_delete(
    file_name: Annotated[
        str,
        PathParameter(
            description="The file name of the archive as GET /api/v2/zim/status lists it, e.g. "
            "wikipedia_de_all_nopic_2026-08.zim; anything but a plain .zim file name - a path, a hidden file - is a 400"
        ),
    ],
    request: Request,
) -> dict[str, Any]:
    """Delete an archive file that is not in use, together with its ``.part`` leftover.

    Meant for a stray download or an archive the profile no longer names. An archive that is active or
    open is refused rather than pulled out from under the running service. Admin only, and it frees the
    disk immediately - the files are gone, not moved.
    """
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
