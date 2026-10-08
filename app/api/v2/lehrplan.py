"""Curriculum endpoints (PLAN.md 8.2): public status and search from the local cache, admin harvest request.

The API process never talks to MEM. ``POST /harvest`` leaves a request file that the harvest loop
(``compendium lehrplan harvest --loop``) picks up; it then checks MEM and harvests when due.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AfterValidator, BeforeValidator

from app.api.admin import require_admin
from app.api.deps import get_service, no_unknown_query
from app.api.gates import GatedRoute
from app.api.keys import require_api_key
from app.api.limits import rate_limited
from app.api.responses import ADMIN_REFUSALS, refusals
from app.compendium.llm_policy import choice_audit, llm_switches
from app.compendium.llm_report import LlmWork, build_llm_report
from app.domain.requests import (
    UNKNOWN_SUBJECT_HELP,
    CurriculumCheck,
    GenerateRequest,
    Preset,
    not_blank,
    with_profile,
)
from app.domain.spelling import readable_value
from app.knowledge.article_choice import ChoiceAudit
from app.knowledge.curriculum_check import CurriculumCheckReport
from app.llm.budget import RequestBudget
from app.llm.deadline import Deadline
from app.service import CompendiumService
from app.settings import Settings
from app.sources.lehrplan.harvest import TRIGGER_FILE, read_status
from app.sources.lehrplan.matcher import CurriculumMatch, build_keywords
from app.sources.lehrplan.part import CurriculaBuilder, match_entry
from app.sources.lehrplan.render import coverage
from app.sources.lehrplan.store import LehrplanCacheError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/lehrplan", tags=["lehrplan"], route_class=GatedRoute)
# What the search takes, which the review page offers as well (app/ui/options.py)
SearchMode = Literal["keyword", "topic"]
QUERY_MIN_CHARS = 3
QUERY_MAX_CHARS = 200
LIMIT_DEFAULT = 50
LIMIT_MIN = 1
LIMIT_MAX = 500
HARVEST_FAILED = (
    "Der letzte Harvest ist gescheitert; den Grund nennen das Log des Harvest-Sidecars "
    "und `compendium lehrplan status`."
)
admin = APIRouter(
    prefix="/api/v2/lehrplan",
    tags=["lehrplan-admin"],
    dependencies=[Depends(rate_limited), Depends(require_admin)],
    responses=ADMIN_REFUSALS,
    route_class=GatedRoute,
)
SEARCH_PRESET_HELP = (
    "The profile, as for part 2 of a compendium (D53, D58, D59). Without it the server's applies (PRESET_DEFAULT, "
    "shipped best-quality-generated; llm-free on a server without an LLM, D68).\n\n"
    "- **llm-free**: the keyword rules find and judge the elements; no LLM, no tokens.\n"
    "- **balanced**: the same for the words as sent; with mode=topic the LLM names the overview and the parts of the "
    "topic and decides an unsure article, as in a balanced compendium (D63), so both search for the same sub-topics; "
    "the question costs about 3.6 s and 480 tokens (M39).\n"
    "- **best-quality**: balanced, and the LLM rates every element the rules found and drops what does not fit "
    "(curriculum_check llm); with mode=topic it also checks a sure article choice of a word with several meanings "
    "(D61). The check spends from a budget of its own, 400,000 tokens per request (LLM_MAX_TOKENS_CURRICULUM_CHECK, "
    "D94).\n"
    "- **best-quality-generated** and **best-coverage-generated**: here the same as best-quality; they differ only in "
    "part 1 of a compendium.\n\n"
    "A profile that needs the LLM for this search - the three best-* profiles always, balanced with mode=topic - is a "
    "503 on a server without one (LLM_ENABLED, B_API_KEY)."
)
SEARCH_CHECK_HELP = (
    "Who judges the elements the rules found (D58); default: the profile's - rule-based in llm-free and balanced, "
    "llm in best-quality, best-quality-generated and best-coverage-generated.\n\n"
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
    choice: ChoiceAudit = field(default_factory=ChoiceAudit)  # the article choice (mode=topic)
    note: str | None = None  # why the LLM could not choose the article


def _as_part_two(request: Request, asked: GenerateRequest, budget: RequestBudget | None, deadline: Deadline) -> _Search:
    """The article, keywords and subject terms that part 2 of a compendium on ``q`` searches for, with the article
    choice of the profile (D35, D59)."""
    service = get_service(request)
    requested, note, job = service.article_choice_job(asked.article_choice, deadline, budget)
    prepared = service.prepare(asked, deadline, job)
    # the same inputs CompendiumService.generate hands to part 2
    keywords, subject_terms = _builder(request).search_terms(
        prepared.title, prepared.aliases, prepared.subtopics, prepared.subjects
    )
    subjects = list(prepared.subjects)
    return _Search(prepared.title, keywords, subject_terms, subjects, choice_audit(prepared, requested), note)


def _llm_answer(
    service: CompendiumService,
    asked: GenerateRequest,
    search: _Search,
    reports: list[CurriculumCheckReport],
    fallback: str | None,
    cached_tokens: int,
) -> tuple[dict[str, Any] | None, dict[str, int] | None]:
    """What the LLM did for the search and what it cost, from the audit of a compendium; ``None`` when not asked.
    ``cached_tokens`` are the prompt tokens of its calls read from the prompt cache (D69)."""
    work = LlmWork(
        note=search.note,
        choice=search.choice,
        curriculum_requested=asked.curriculum_check or "rule-based",
        curriculum=reports[0] if reports else None,
        curriculum_fallback=fallback,
        cached_tokens=cached_tokens,
    )
    audit, tokens, _ = build_llm_report(service.llm, work)
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


@router.get(
    "/search",
    dependencies=[Depends(rate_limited), Depends(require_api_key), Depends(no_unknown_query)],
    responses=refusals(401, 404, 422, 429, 503),  # no repository behind it: no 502
)
def lehrplan_search(
    request: Request,
    # both in one spelling before their bounds, which then count what is searched (app/domain/spelling.py)
    q: Annotated[
        str,
        BeforeValidator(readable_value),
        Query(
            min_length=QUERY_MIN_CHARS,
            max_length=QUERY_MAX_CHARS,
            description=f"The keyword (mode keyword) or the topic (mode topic), {QUERY_MIN_CHARS} to {QUERY_MAX_CHARS} "
            "characters; blanks alone are a 422",
        ),
        AfterValidator(not_blank),  # it is the topic of the request as well (audit 2026-09-29, S9)
    ],
    subject: Annotated[
        str | None,
        BeforeValidator(readable_value),
        Query(
            max_length=100,
            description="WLO discipline id, URI, label or alias; it narrows the search only when config/subjects.yaml "
            "gives it curriculum words (37 subjects), any other one leaves subject_terms empty" + UNKNOWN_SUBJECT_HELP,
        ),
    ] = None,
    limit: int = Query(
        LIMIT_DEFAULT,
        ge=LIMIT_MIN,
        le=LIMIT_MAX,
        description=f"How many elements come back, the best first: {LIMIT_MIN} to {LIMIT_MAX}, default "
        f"{LIMIT_DEFAULT}. It bounds the answer, not the search or the LLM check; total_hits says how many elements "
        "the search found. It ranks 20,000 of them at most: cut_hits says how many lay beyond, and the ones of the "
        "strongest roles stay (Themenbereich, Kompetenz, Inhalt)",
    ),
    mode: Annotated[
        SearchMode,
        Query(
            description="keyword: the words as sent; topic: what part 2 of a compendium on q searches for - the "
            "article of the topic, its aliases and the sub-topics of its corpus, with the subjects of the topic",
        ),
    ] = "keyword",
    preset: Annotated[Preset | None, Query(description=SEARCH_PRESET_HELP)] = None,
    curriculum_check: Annotated[CurriculumCheck | None, Query(description=SEARCH_CHECK_HELP)] = None,
) -> dict[str, Any]:
    """Curriculum elements for a keyword or a topic, out of the local cache: the ones part 2 of a compendium lists,
    found by the same rules and, in the three best-* profiles, judged by the same LLM check. MEM is never asked.

    **What it searches.** ``q`` is the keyword, ``subject`` narrows it to the curricula of one subject and ``limit``
    bounds the answer. By default (``mode=keyword``) it searches the words as sent; ``mode=topic`` resolves ``q`` as
    part 2 of a compendium does - the article of the topic, its aliases and the sub-topics of its corpus, with the
    subjects of the topic -, names the article in ``topic`` and answers 404 for a topic the archives do not have.
    There a side word of the article that stands in more elements of the cache than LEHRPLAN_GENERIC_WORD_HITS
    (1,000; "Gruppe", "Musik") is too general and not searched, as in part 2; ``generic_keywords`` names it (D80).
    The words of ``mode=keyword`` are searched as sent. The ranking is the one part 2 uses.

    **What each profile does here.** ``preset`` picks it as for a compendium; without it the server's applies
    (PRESET_DEFAULT, shipped best-quality-generated; llm-free on a server without an LLM, D68), and a
    ``curriculum_check`` of the request wins over the profile's.

    - ``llm-free``: the rules find and judge; no LLM, no tokens.
    - ``balanced``: the same for the words as sent; with ``mode=topic`` the LLM names the overview and the parts of
      the topic and decides an unsure article, as in a balanced compendium (D63), so both search for the same
      sub-topics; the question costs about 3.6 s and 480 tokens (M39).
    - ``best-quality``: balanced, and the LLM rates every element the rules found and drops what does not fit; the
      others carry its rating in ``note``. With ``mode=topic`` it also checks a sure article choice of a word with
      several meanings (D61). It reads all hits, not only the first ``limit`` ones: 80 to 90 tokens per
      element, from a budget of its own, 400,000 tokens per request (LLM_MAX_TOKENS_CURRICULUM_CHECK, D94) -
      Demokratie without a subject, 819 hits, took 75,016 tokens (M33). What the budget or the time leaves unrated
      keeps the rules' decision.
    - ``best-quality-generated`` and ``best-coverage-generated``: here the same as best-quality; they differ only in
      part 1 of a compendium.

    **What comes back.** Every element with its curriculum and where it stands: federal state, school type, school
    level and grade, the last two with their source (``schulstufe_quelle``, ``klassenstufe_quelle``), the keyword
    that found it and ``matched_in`` - ``label`` when the element names the topic, ``parent`` when only its heading
    does; part 2 counts those with their area unless the LLM rates them fitting, and after the LLM check every
    element it rates 1 as well (D80). ``preset`` names the profile in effect, ``llm`` what the LLM did (article
    choice, check) and ``llm_tokens`` what it cost; both are ``null`` when no LLM was asked.

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
    builder.subjects.check(subject)
    service: CompendiumService = request.app.state.service
    asked = with_profile(
        GenerateRequest(
            topic=q, subject=subject, parts=["curricula"], preset=preset, curriculum_check=curriculum_check
        ),
        service.default_preset,
    )
    profile = asked.preset or service.default_preset
    # the words alone need no article, so only mode=topic can need the LLM for one
    service.refuse_without_llm(llm_switches(asked, corpus=mode == "topic"), profile, defaulted=preset is None)
    budget, deadline = service.open_budget(profile), Deadline(service.settings.request_time_limit_s)
    if mode == "topic":
        search = _as_part_two(request, asked, budget, deadline)
    else:
        keywords = build_keywords(q, aliases=[], subtopics=[])
        search = _Search(None, keywords, builder.subjects.mem_terms(subject), [subject] if subject else [])
    asked_for = {"mode": mode, "topic": search.topic, "preset": profile}
    reports: list[CurriculumCheckReport] = []
    fallback: str | None = None
    check_budget: RequestBudget | None = None  # the check spends from its own (D94)
    matches: list[CurriculumMatch] = []
    result = None
    if builder.store.available:
        try:
            # the words of a topic's article lose the too general ones, as in part 2; words sent stay as they are
            matcher = builder.matcher(topic=mode == "topic")
            result = matcher.match(search.keywords, subject_terms=search.subject_terms)
        except LehrplanCacheError as exc:
            log.error("%s", exc)
    if result is not None and result.matches:
        matches = result.matches
        if asked.curriculum_check == "llm":  # all of them, as part 2 checks them
            check_budget = service.open_check_budget()
            check, fallback = service.curriculum_check(
                search.topic or q, search.subjects, check_budget, deadline, reports
            )
            if check is not None:
                matches = check(matches)
    cached = sum(spent.cached_tokens for spent in (budget, check_budget) if spent is not None)
    llm, tokens = _llm_answer(service, asked, search, reports, fallback, cached)
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
        "generic_keywords": result.generic_keywords,
        "subject_terms": result.subject_terms,
        "total_hits": result.total_hits,
        "cut_hits": result.cut_hits,
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
    log.info("curriculum harvest requested via API; the updater checks MEM at its next poll")
    return {
        "requested": True,
        "note": "Der Harvest-Job (compendium lehrplan harvest --loop) prüft beim nächsten Poll gegen MEM und "
        "zieht die Lehrpläne neu, wenn sich die Zählung geändert hat oder der Cache älter als "
        "LEHRPLAN_HARVEST_MAX_AGE ist.",
    }
