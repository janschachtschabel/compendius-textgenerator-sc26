"""Curriculum endpoints (PLAN.md 8.2): public status and search from the local cache, admin harvest request.

The API process never talks to MEM. ``POST /harvest`` leaves a request file that the harvest loop
(``compendium lehrplan harvest --loop``) picks up; it then checks MEM and harvests when due.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.admin import require_admin
from app.api.limits import rate_limited
from app.settings import Settings
from app.sources.lehrplan.harvest import TRIGGER_FILE, read_status
from app.sources.lehrplan.matcher import LehrplanMatcher, build_keywords
from app.sources.lehrplan.part import CurriculaBuilder, match_entry
from app.sources.lehrplan.render import coverage
from app.sources.lehrplan.store import LehrplanCacheError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/lehrplan", tags=["lehrplan"])
HARVEST_FAILED = (
    "Der letzte Harvest ist gescheitert; den Grund nennen das Log des Harvest-Sidecars "
    "und `compendium lehrplan status`."
)
admin = APIRouter(prefix="/api/v2/lehrplan", tags=["lehrplan-admin"], dependencies=[Depends(require_admin)])


def _public_harvest(status: dict[str, Any] | None) -> dict[str, Any] | None:
    """The harvest status without the error text, which can name server paths; the file and the log keep it."""
    if status is None:
        return None
    public = {key: status.get(key) for key in ("state", "updated_at", "started_at", "progress", "last_run")}
    public["error"] = HARVEST_FAILED if status.get("error") else None
    return public


def _builder(request: Request) -> CurriculaBuilder:
    builder: CurriculaBuilder = request.app.state.curricula
    return builder


@router.get("/status")
def lehrplan_status(request: Request) -> dict[str, Any]:
    """Cache presence, harvest metadata, curricula per state and the harvest job's last status."""
    settings: Settings = request.app.state.settings
    store = _builder(request).store
    meta = store.meta()
    return {
        "available": store.available,
        "file_present": store.exists,
        "meta": meta,
        "counts": store.counts(),
        "coverage": coverage(meta),
        "harvest": _public_harvest(read_status(Path(settings.state_dir))),
    }


@router.get("/search", dependencies=[Depends(rate_limited)])
def lehrplan_search(
    request: Request,
    q: str = Query(..., min_length=3, max_length=200, description="Topic or keyword"),
    subject: str | None = Query(None, max_length=100, description="WLO discipline id, URI, label or alias"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Curriculum elements for a keyword, ranked like part 2; local, no MEM access."""
    builder = _builder(request)
    keywords = build_keywords(q, aliases=[], subtopics=[])
    subject_terms = builder.subjects.mem_terms(subject)
    if not builder.store.available:
        return {"available": False, "keywords": keywords, "subject_terms": subject_terms, "matches": []}
    try:
        result = LehrplanMatcher(builder.store).match(keywords, subject_terms=subject_terms)
    except LehrplanCacheError as exc:
        log.error("%s", exc)
        return {"available": False, "keywords": keywords, "subject_terms": subject_terms, "matches": []}
    return {
        "available": True,
        "keywords": result.keywords,
        "subject_terms": result.subject_terms,
        "total_hits": result.total_hits,
        "excluded_noise": result.excluded_noise,
        "matches": [match_entry(match) for match in result.matches[:limit]],
    }


@admin.post("/harvest", status_code=202)
def lehrplan_harvest_now(request: Request) -> dict[str, Any]:
    """Ask the harvest loop to check MEM now; this process fetches nothing."""
    state_dir = Path(request.app.state.settings.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / TRIGGER_FILE).write_text("requested via API\n", encoding="utf-8")
    return {
        "requested": True,
        "note": "Der Harvest-Job (compendium lehrplan harvest --loop) prüft beim nächsten Poll gegen MEM und "
        "zieht die Lehrpläne neu, wenn sich die Zählung geändert hat oder der Cache älter als "
        "LEHRPLAN_HARVEST_MAX_AGE ist.",
    }
