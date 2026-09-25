"""Curriculum endpoints (PLAN.md 8.2): public status and search from the local cache, admin harvest request.

The API process never talks to MEM. ``POST /harvest`` leaves a request file that the harvest loop
(``compendium lehrplan harvest --loop``) picks up; it then checks MEM and harvests when due.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.admin import require_admin
from app.api.deps import get_service
from app.api.limits import rate_limited
from app.domain.requests import GenerateRequest
from app.service import TopicNotFoundError
from app.settings import Settings
from app.sources.lehrplan.harvest import TRIGGER_FILE, read_status
from app.sources.lehrplan.matcher import LehrplanMatcher, build_keywords
from app.sources.lehrplan.part import CurriculaBuilder, match_entry
from app.sources.lehrplan.render import coverage
from app.sources.lehrplan.store import LehrplanCacheError
from app.sources.lehrplan.subjects import UnknownSubjectError

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


def _as_part_two(request: Request, q: str, subject: str | None) -> tuple[str, list[str], list[str]]:
    """The article, keywords and subject terms that part 2 of a compendium on ``q`` searches for, by the rules."""
    service = get_service(request)
    try:
        prepared = service.prepare(GenerateRequest(topic=q, subject=subject, parts=["curricula"]))
    except TopicNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail()) from exc
    # as CompendiumService.generate hands them to part 2
    title = prepared.resolution.title or prepared.normalized.topic
    primary = next((s for s in prepared.sources if s.is_primary), prepared.sources[0] if prepared.sources else None)
    keywords = build_keywords(title, aliases=list(primary.aliases) if primary else [], subtopics=prepared.subtopics)
    return title, keywords, _builder(request).subjects.mem_terms_of(prepared.subjects)


@router.get("/status")
def lehrplan_status(request: Request) -> dict[str, Any]:
    """What the curriculum cache holds and how fresh it is.

    Whether the cache is there at all, when it was harvested, how many curricula per federal state it
    carries and what the harvest job last reported - including whether it failed. The error text stays
    out: it can name server paths. The file and the log keep it.

    Part 2 of a compendium reads this cache; an empty one is why ``parts: ["curricula"]`` comes back
    thin. The sidecar fills it, ``POST /api/v2/lehrplan/harvest`` asks it to check now.
    """
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
    mode: Literal["keyword", "topic"] = Query(
        "keyword",
        description="keyword: the words as sent; topic: what part 2 of a compendium on q searches for - the article "
        "of the topic, its aliases and the sub-topics of its corpus, with the subjects of the topic",
    ),
) -> dict[str, Any]:
    """Curriculum elements for a keyword or a topic, out of the local cache - no MEM access, no network.

    ``q`` is the keyword, ``subject`` narrows it to one subject and ``limit`` bounds the hits. The ranking is the
    one part 2 uses. By default it searches the words as sent; ``mode=topic`` resolves ``q`` as part 2 of a
    compendium does, by the rules and without an LLM, names the article in ``topic`` and answers 404 for a topic
    the archives do not have. A subject the catalog does not know is a 422 that lists the known ones.

    An empty answer usually means an empty cache rather than no match; ``GET /api/v2/lehrplan/status``
    says which it is.
    """
    builder = _builder(request)
    try:
        builder.subjects.check(subject)
    except UnknownSubjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if mode == "topic":
        topic, keywords, subject_terms = _as_part_two(request, q, subject)
    else:
        topic, keywords = None, build_keywords(q, aliases=[], subtopics=[])
        subject_terms = builder.subjects.mem_terms(subject)
    asked = {"mode": mode, "topic": topic}
    if not builder.store.available:
        return {"available": False, **asked, "keywords": keywords, "subject_terms": subject_terms, "matches": []}
    try:
        result = LehrplanMatcher(builder.store).match(keywords, subject_terms=subject_terms)
    except LehrplanCacheError as exc:
        log.error("%s", exc)
        return {"available": False, **asked, "keywords": keywords, "subject_terms": subject_terms, "matches": []}
    return {
        "available": True,
        **asked,
        "keywords": result.keywords,
        "subject_terms": result.subject_terms,
        "total_hits": result.total_hits,
        "excluded_noise": result.excluded_noise,
        "matches": [match_entry(match) for match in result.matches[:limit]],
    }


@admin.post("/harvest", status_code=202)
def lehrplan_harvest_now(request: Request) -> dict[str, Any]:
    """Ask the harvest sidecar to check MEM now.

    This process fetches nothing: it writes a request file that the sidecar polls, so the answer says the
    request was placed, not that a harvest ran. ``GET /api/v2/lehrplan/status`` shows what came of it.
    Admin only.
    """
    state_dir = Path(request.app.state.settings.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / TRIGGER_FILE).write_text("requested via API\n", encoding="utf-8")
    return {
        "requested": True,
        "note": "Der Harvest-Job (compendium lehrplan harvest --loop) prüft beim nächsten Poll gegen MEM und "
        "zieht die Lehrpläne neu, wenn sich die Zählung geändert hat oder der Cache älter als "
        "LEHRPLAN_HARVEST_MAX_AGE ist.",
    }
