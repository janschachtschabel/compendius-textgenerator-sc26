"""Curriculum endpoints (PLAN.md 8.2): public status and search from the local cache, admin harvest request.

The API process never talks to MEM. ``POST /harvest`` leaves a request file that the harvest loop
(``compendium lehrplan harvest --loop``) picks up; it then checks MEM and harvests when due.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.admin import require_admin
from app.api.deps import get_service
from app.api.limits import rate_limited
from app.domain.requests import UNKNOWN_SUBJECT_HELP, CurriculumCheck, GenerateRequest, Preset, with_profile
from app.knowledge.curriculum_check import CurriculumCheckReport
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.llm.report import build_llm_report
from app.service import CompendiumService, LlmNotConfiguredError, TopicNotFoundError, choice_audit, llm_switches
from app.settings import Settings
from app.sources.lehrplan.harvest import TRIGGER_FILE, read_status
from app.sources.lehrplan.matcher import CurriculumMatch, LehrplanMatcher, build_keywords
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
SEARCH_PRESET_HELP = (
    "The profile, as for part 2 of a compendium (D53, D58, D59). Without it the server's applies (PRESET_DEFAULT, "
    "shipped balanced).\n\n"
    "- **llm-free**: the keyword rules find and judge the elements; no LLM, no tokens.\n"
    "- **balanced**: the same for the words as sent; with mode=topic the LLM decides an unsure article and drops the "
    "side articles that do not fit, as in a balanced compendium, so both search for the same sub-topics.\n"
    "- **best-quality**: balanced, and the LLM rates every element the rules found and drops what does not fit "
    "(curriculum_check llm). It spends from LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY, 180,000 tokens per request.\n"
    "- **best-quality-generated**: here the same as best-quality; the two differ only in part 1 of a compendium.\n\n"
    "A profile that needs the LLM for this search - best-quality and best-quality-generated always, balanced with "
    "mode=topic - is a 503 on a server without one (LLM_ENABLED, B_API_KEY)."
)
SEARCH_CHECK_HELP = (
    "Who judges the elements the rules found (D58); default: the profile's - rule-based in llm-free and balanced, "
    "llm in best-quality and best-quality-generated.\n\n"
    "- **rule-based**: the keyword rules alone. An element that names the topic only in its heading comes back with "
    "matched_in parent; part 2 of a compendium counts those with their area. Over the 20 topics of M22, 70 to 81 % "
    "of what part 2 lists fits (M32).\n"
    "- **llm**: the LLM of the b-api rates every element with its area and curriculum - 2 fits, 1 touches the topic, "
    "0 does not fit - and what does not fit leaves the answer; the others carry the rating in note. It reads all "
    "hits, not only the first limit ones: 80 to 90 tokens per element, and total_hits says how many there are. 74 "
    "to 79 % fit, and no element two raters called fitting was dropped (M32). What the budget or the time leaves "
    "unrated keeps the rules' decision, and llm.curriculum_check says why. Without a configured LLM a 503."
)


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


@dataclass(frozen=True)
class _Search:
    """What the search looks for: the words, the subject terms and, with mode=topic, the article and how it came."""

    topic: str | None
    keywords: list[str]
    subject_terms: list[str]
    subjects: list[str]  # as the request or the topic named them, for the LLM check
    choice: dict[str, Any] = field(default_factory=dict)  # build_llm_report on the article choice (mode=topic)
    note: str | None = None  # why the LLM could not choose the article


def _as_part_two(request: Request, asked: GenerateRequest, budget: RequestBudget | None, deadline: Deadline) -> _Search:
    """The article, keywords and subject terms that part 2 of a compendium on ``q`` searches for, with the article
    choice of the profile (D35, D59)."""
    service = get_service(request)
    requested, note, job = service.article_choice_job(asked.article_choice, deadline, budget)
    try:
        prepared = service.prepare(asked, deadline, job)
    except TopicNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail()) from exc
    # as CompendiumService.generate hands them to part 2
    title = prepared.resolution.title or prepared.normalized.topic
    primary = next((s for s in prepared.sources if s.is_primary), prepared.sources[0] if prepared.sources else None)
    keywords = build_keywords(title, aliases=list(primary.aliases) if primary else [], subtopics=prepared.subtopics)
    subject_terms = _builder(request).subjects.mem_terms_of(prepared.subjects)
    return _Search(title, keywords, subject_terms, list(prepared.subjects), choice_audit(prepared, requested), note)


def _llm_answer(
    service: CompendiumService,
    asked: GenerateRequest,
    search: _Search,
    reports: list[CurriculumCheckReport],
    fallback: str | None,
) -> tuple[dict[str, Any] | None, dict[str, int] | None]:
    """What the LLM did for the search and what it cost, from the audit of a compendium; ``None`` when not asked."""
    audit, tokens, _ = build_llm_report(
        service.llm,
        extraction_requested="rule-based",
        extraction_used="rule-based",
        generation_requested="rule-based",
        generation_used="rule-based",
        enrichment_requested="sources-only",
        enrichment_used="sources-only",
        note=search.note,
        extraction=None,
        generation=None,
        **search.choice,
        curriculum_requested=asked.curriculum_check or "rule-based",
        curriculum=reports[0] if reports else None,
        curriculum_fallback=fallback,
    )
    if audit is None:
        return None, None
    return {key: audit[key] for key in ("note", "article_choice", "curriculum_check")}, tokens


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
    q: str = Query(
        ...,
        min_length=3,
        max_length=200,
        description="The keyword (mode keyword) or the topic (mode topic), 3 to 200 characters",
    ),
    subject: str | None = Query(
        None,
        max_length=100,
        description="WLO discipline id, URI, label or alias; it narrows the search only when config/subjects.yaml "
        "gives it curriculum words (37 subjects), any other one leaves subject_terms empty" + UNKNOWN_SUBJECT_HELP,
    ),
    limit: int = Query(
        50,
        ge=1,
        le=500,
        description="How many elements come back, the best first: 1 to 500, default 50. It bounds the answer, not the "
        "search or the LLM check; total_hits says how many the rules found",
    ),
    mode: Literal["keyword", "topic"] = Query(
        "keyword",
        description="keyword: the words as sent; topic: what part 2 of a compendium on q searches for - the article "
        "of the topic, its aliases and the sub-topics of its corpus, with the subjects of the topic",
    ),
    preset: Annotated[Preset | None, Query(description=SEARCH_PRESET_HELP)] = None,
    curriculum_check: Annotated[CurriculumCheck | None, Query(description=SEARCH_CHECK_HELP)] = None,
) -> dict[str, Any]:
    """Curriculum elements for a keyword or a topic, out of the local cache: the ones part 2 of a compendium lists,
    found by the same rules and, in the best-quality profiles, judged by the same LLM check. MEM is never asked.

    **What it searches.** ``q`` is the keyword, ``subject`` narrows it to the curricula of one subject and ``limit``
    bounds the answer. By default (``mode=keyword``) it searches the words as sent; ``mode=topic`` resolves ``q`` as
    part 2 of a compendium does - the article of the topic, its aliases and the sub-topics of its corpus, with the
    subjects of the topic -, names the article in ``topic`` and answers 404 for a topic the archives do not have.
    The ranking is the one part 2 uses.

    **What each profile does here.** ``preset`` picks it as for a compendium; without it the server's applies
    (PRESET_DEFAULT, shipped balanced), and a ``curriculum_check`` of the request wins over the profile's.

    - ``llm-free``: the rules find and judge; no LLM, no tokens.
    - ``balanced``: the same for the words as sent; with ``mode=topic`` the LLM decides an unsure article and drops
      the side articles that do not fit, as in a balanced compendium, so both search for the same sub-topics.
    - ``best-quality``: balanced, and the LLM rates every element the rules found and drops what does not fit; the
      others carry its rating in ``note``. It reads all hits, not only the first ``limit`` ones: 80 to 90 tokens per
      element, from 180,000 tokens per request (LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY, D59) - Demokratie without a
      subject, 819 hits, took 75,016 tokens (M33). What the budget or the time leaves unrated keeps the rules'
      decision.
    - ``best-quality-generated``: here the same as best-quality; the two differ only in part 1 of a compendium.

    **What comes back.** Every element with its curriculum and where it stands: federal state, school type, school
    level and grade, the last two with their source (``schulstufe_quelle``, ``klassenstufe_quelle``), the keyword
    that found it and ``matched_in`` - ``label`` when the element names the topic, ``parent`` when only its heading
    does; part 2 counts those with their area unless the LLM rates them fitting. ``preset`` names the profile in
    effect, ``llm`` what the LLM did (article choice, check) and ``llm_tokens`` what it cost; both are ``null`` when
    no LLM was asked.

    **When it refuses.** A profile or ``curriculum_check`` that needs an LLM on a server without one: 503. A subject
    outside the two subject vocabularies of edu-sharing: 422 that lists the school subjects; only the 37 subjects of
    config/subjects.yaml have curriculum words, any other one narrows nothing and ``subject_terms`` stays empty
    (D51). An empty answer usually means an empty cache rather than no match; ``GET /api/v2/lehrplan/status`` says
    which it is.

    **Examples** of ``GET``, from the shortest to every parameter:

    - ``/api/v2/lehrplan/search?q=Optik``
    - ``/api/v2/lehrplan/search?q=Optik&subject=Physik&limit=20``
    - ``/api/v2/lehrplan/search?q=Linse&subject=Physik&mode=topic&preset=balanced`` - an ambiguous topic whose
      article the LLM decides in balanced, as in a compendium
    - ``/api/v2/lehrplan/search?q=Optik&subject=Physik&mode=topic&limit=100&preset=best-quality&curriculum_check=llm``
    """
    builder = _builder(request)
    try:
        builder.subjects.check(subject)
    except UnknownSubjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    service: CompendiumService = request.app.state.service
    asked = with_profile(
        GenerateRequest(
            topic=q, subject=subject, parts=["curricula"], preset=preset, curriculum_check=curriculum_check
        ),
        service.settings.preset_default,
    )
    profile = asked.preset or service.settings.preset_default
    try:  # the words alone need no article, so only mode=topic can need the LLM for one
        service.refuse_without_llm(llm_switches(asked, corpus=mode == "topic"), profile, defaulted=preset is None)
    except LlmNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    budget, deadline = service.open_budget(profile), Deadline(service.settings.request_timeout_s)
    if mode == "topic":
        search = _as_part_two(request, asked, budget, deadline)
    else:
        keywords = build_keywords(q, aliases=[], subtopics=[])
        search = _Search(None, keywords, builder.subjects.mem_terms(subject), [subject] if subject else [])
    asked_for = {"mode": mode, "topic": search.topic, "preset": profile}
    reports: list[CurriculumCheckReport] = []
    fallback: str | None = None
    matches: list[CurriculumMatch] = []
    result = None
    if builder.store.available:
        try:
            result = LehrplanMatcher(builder.store).match(search.keywords, subject_terms=search.subject_terms)
        except LehrplanCacheError as exc:
            log.error("%s", exc)
    if result is not None and result.matches:
        matches = result.matches
        if asked.curriculum_check == "llm":  # all of them, as part 2 checks them
            check, fallback = service.curriculum_check(search.topic or q, search.subjects, budget, deadline, reports)
            if check is not None:
                matches = check(matches)
    llm, tokens = _llm_answer(service, asked, search, reports, fallback)
    if result is None:
        return {
            "available": False,
            **asked_for,
            "keywords": search.keywords,
            "subject_terms": search.subject_terms,
            "matches": [],
            "llm": llm,
            "llm_tokens": tokens,
        }
    return {
        "available": True,
        **asked_for,
        "keywords": result.keywords,
        "subject_terms": result.subject_terms,
        "total_hits": result.total_hits,
        "excluded_noise": result.excluded_noise,
        "matches": [match_entry(match) for match in matches[:limit]],
        "llm": llm,
        "llm_tokens": tokens,
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
