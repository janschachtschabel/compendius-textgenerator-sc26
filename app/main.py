"""FastAPI application factory. Start with ``uvicorn app.main:create_app --factory``."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import iter_route_contexts
from starlette.exceptions import HTTPException
from starlette.routing import BaseRoute, Match
from starlette.types import Scope

from app import __version__
from app.api.body_limit import BodySizeLimit
from app.api.docs import docs_router
from app.api.domain_errors import DOMAIN_ERRORS
from app.api.errors import JsonResponse, http_error, validation_error
from app.api.health import router as health_router
from app.api.limits import RateLimiter
from app.api.metrics import METRICS_PATH, name_the_route
from app.api.metrics import router as metrics_router
from app.api.system_threads import run_system, system_limiter
from app.api.v2.collections import router as collections_router
from app.api.v2.entities import router as entities_router
from app.api.v2.knowledge import router as knowledge_router
from app.api.v2.lehrplan import admin as lehrplan_admin_router
from app.api.v2.lehrplan import router as lehrplan_router
from app.api.v2.matching import router as matching_router
from app.api.v2.nodes import router as nodes_router
from app.api.v2.qa import router as qa_router
from app.api.v2.routes import admin as v2_admin_router
from app.api.v2.routes import router as v2_router
from app.api.v2.zim import admin as zim_admin_router
from app.api.v2.zim import router as zim_router
from app.compendium.gateway import LlmGateway, LlmOptions
from app.knowledge.recognise import load_spacy
from app.llm.budget import DailyStore, TokenBudget
from app.llm.budget_store import SqliteDailyStore
from app.llm.call import listen_to_calls
from app.llm.client import BApiClient, is_reasoning_model
from app.llm.deadline import MIN_CALL_S
from app.logging import REQUEST_ID_HEADER, configure_logging, current_request_id, set_request_id
from app.matching.lexicon import HeadingLexicon
from app.matching.registry import LOCAL_MATCHER, active_components
from app.observability.metrics import UNMATCHED_ROUTE, observe_request, record_llm_call
from app.service import CompendiumService
from app.settings import Settings, b_api_for, get_settings
from app.sources.gnd.index import GndIndex
from app.sources.lehrplan.part import CurriculaBuilder
from app.sources.lehrplan.render import RenderOptions
from app.sources.lehrplan.store import LehrplanStore
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.wikidata.index import WikidataIndex
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.knowledge import KnowledgeOptions
from app.sources.wlo.overview import OverviewOptions
from app.sources.wlo.part import CollectionBuilder, CollectionOptions
from app.sources.zim.catalog import OPDS_DEFAULT_URL, KiwixCatalog
from app.sources.zim.refresh import RegistryRefresher
from app.sources.zim.registry import ZimRegistry
from app.sources.zim.subscriptions import SubscriptionManifest, load_manifest
from app.synthesis.facets import FacetCatalog
from app.templates.manager import SHIPPED_DEFAULT, TemplateManager, TemplateNotFoundError
from app.ui.routes import ui_router

log = logging.getLogger(__name__)

OPENAPI_PATH = "/openapi.json"

# Up to this REQUEST_TIMEOUT_S the LLM gets hardly a call (audit 2026-09-29, S6): a call starts only while MIN_CALL_S
# remain (app/llm/deadline.py) and has to be answered by the end of the request, so it must start in the request's
# first seconds and be done within ten. The quickest LLM steps measured took about 4 s - the article choice 3.6 s
# (M39), naming the entities 4 s (M36) -, a call of the matching or the writing longer.
SHORTEST_LLM_TIMEOUT_S = 2 * MIN_CALL_S
# The values OpenAI documents for its reasoning models, GPT-5 to GPT-5.2 (the audit's list and xhigh). A reasoning model
# gets both settings as they stand, so a typo would likely fail every call with a 400 while /health says available; a
# newer model may know more, so an unknown value is a warning (audit 2026-09-29, S7)
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
VERBOSITIES = ("low", "medium", "high")


def build_registry(settings: Settings) -> ZimRegistry:
    """Explicit ZIM_PATHS win (development, tests); otherwise active.json in ZIM_DIR decides."""
    if settings.zim_path_list:
        # It is meant for development, but it also runs in production, where it quietly turns off the archive
        # management an operator expects (docs/umbau.md U6). Saying so at start beats finding out later.
        log.warning(
            "ZIM_PATHS umgeht die Archivverwaltung: active.json wird nicht gelesen, der Sync-Job verwaltet "
            "diese Archive nicht, und ein Wechsel braucht einen Neustart. Für den Betrieb ZIM_PATHS leer "
            "lassen und ZIM_DIR=%s verwenden. Geladen aus: %s",
            settings.zim_dir,
            settings.zim_paths,
        )
        return ZimRegistry(settings.zim_path_list)
    return ZimRegistry.from_active(settings.zim_dir)


def load_subscriptions(settings: Settings) -> SubscriptionManifest | None:
    path = settings.zim_manifest_path
    if not path.exists():
        log.warning("subscription manifest not found at %s; readiness relies on ZIM_REQUIRED", path)
        return None
    return load_manifest(path)


def resolve_required_ids(settings: Settings, manifest: SubscriptionManifest | None) -> list[str]:
    """ZIM_REQUIRED wins; otherwise the manifest decides for ZIM_PROFILE."""
    if settings.zim_required_ids or manifest is None:
        return settings.zim_required_ids
    return manifest.required_ids(settings.zim_profile)


def build_service(settings: Settings, registry: ZimRegistry, templates: TemplateManager) -> CompendiumService:
    lexicon_path = Path(settings.config_dir) / "heading_lexicon.yaml"
    facets_path = Path(settings.config_dir) / "facets.yaml"
    lexicon = HeadingLexicon.load(lexicon_path) if lexicon_path.exists() else HeadingLexicon.empty()
    facets = FacetCatalog.load(facets_path) if facets_path.exists() else FacetCatalog.empty()
    if not lexicon_path.exists():
        log.warning("heading lexicon not found at %s; matching runs without stage 1", lexicon_path)
    return CompendiumService(
        registry=registry,
        templates=templates,
        lexicon=lexicon,
        facets=facets,
        settings=settings,
        curricula=build_curricula(settings),
        collections=build_collections(settings),
        llm=build_llm(settings),
    )


def resolve_b_api(settings: Settings) -> str:
    """The b-api address to call: the configured one, otherwise the one belonging to the repository."""
    belongs_to_repository = b_api_for(settings.edu_sharing_base_url)
    if not settings.b_api_base_url:
        if not belongs_to_repository:
            log.warning(
                "B_API_BASE_URL is empty and %s is not one of the known repositories, so no b-api can be derived",
                settings.edu_sharing_base_url or "(no repository)",
            )
        return settings.b_api_url
    if belongs_to_repository and settings.b_api_base_url.rstrip("/") != belongs_to_repository:
        log.warning(
            "B_API_BASE_URL=%s does not belong to the repository %s, whose b-api is %s; using the configured one",
            settings.b_api_base_url,
            settings.edu_sharing_base_url,
            belongs_to_repository,
        )
    return settings.b_api_url


def warn_about_llm_settings(settings: Settings) -> None:
    """Settings the LLM can hardly work with, named at start; the service keeps them (a warning, not a refusal: a
    stricter check stopped all containers on 2026-09-28, BE-13)."""
    if settings.request_timeout_s <= SHORTEST_LLM_TIMEOUT_S:
        log.warning(
            "REQUEST_TIMEOUT_S=%d leaves the LLM hardly a call: one starts only while %g s of the request remain and "
            "has to be answered by its end, and the quickest LLM steps take about 4 s, the matching and the writing "
            "longer; the LLM steps fall back to the rules. The default is %d s (audit 2026-09-29, S6)",
            settings.request_timeout_s,
            MIN_CALL_S,
            Settings.model_fields["request_timeout_s"].default,
        )
    if not settings.llm_daily_token_budget and not settings.api_key_list:
        log.warning(
            "LLM_DAILY_TOKEN_BUDGET=0 and API_KEYS empty: anyone who reaches the service spends b-api tokens without a "
            "daily cap. Set API_KEYS, or a cap in LLM_DAILY_TOKEN_BUDGET (D67)"
        )
    if not is_reasoning_model(settings.b_api_model):
        return  # a classic model is sent neither
    for name, value, known in (
        ("LLM_REASONING_EFFORT", settings.llm_reasoning_effort, REASONING_EFFORTS),
        ("LLM_VERBOSITY", settings.llm_verbosity, VERBOSITIES),
    ):
        if value not in known:
            log.warning(
                "%s=%r is not one of %s: %s gets it as it stands and may refuse every call with a 400 while /health "
                "says the LLM is available; a newer model may know the value (audit 2026-09-29, S7)",
                name,
                value,
                ", ".join(known),
                settings.b_api_model,
            )


def build_llm(settings: Settings) -> LlmGateway | None:
    """The b-api gateway for the LLM switches (PLAN.md 7); off without LLM_ENABLED or without a key."""
    if not settings.llm_enabled:
        return None
    if not settings.b_api_key:
        log.warning("LLM_ENABLED is set but B_API_KEY is empty; LLM requests fall back to the rule-based path")
        return None
    base_url = resolve_b_api(settings)
    if not base_url:
        log.warning("LLM_ENABLED is set but no b-api address is known; LLM requests fall back to the rule-based path")
        return None
    warn_about_llm_settings(settings)
    client = BApiClient(
        base_url,
        settings.b_api_key,
        provider=settings.b_api_provider,
        model=settings.b_api_model,
        timeout_s=settings.llm_timeout_s,
        max_concurrency=settings.llm_max_concurrency,
        attempts=settings.llm_attempts,
        reasoning_effort=settings.llm_reasoning_effort,
        verbosity=settings.llm_verbosity,
        temperature=settings.llm_temperature,
    )
    store: DailyStore | None = None
    try:
        store = SqliteDailyStore(settings.llm_budget_path)  # one daily counter for all workers, kept across restarts
    except (sqlite3.Error, OSError) as exc:
        log.warning(
            "LLM budget store unavailable at %s (%s); the daily budget counts per process",
            settings.llm_budget_path,
            exc,
        )
    budget = TokenBudget(
        per_request=settings.llm_max_tokens_per_request, daily=settings.llm_daily_token_budget, store=store
    )
    options = LlmOptions(
        fast_sections=tuple(settings.llm_fast_section_ids),
        extraction_candidates=settings.llm_extraction_candidates,
        concurrency=settings.llm_max_concurrency,
        mark_unsupported=settings.llm_unsupported_sentences == "mark",
    )
    gateway = LlmGateway(client, budget, options)
    gateway.check_model()  # warns only; an unavailable model means rule-based answers until it is back
    return gateway


def build_collections(settings: Settings) -> CollectionBuilder | None:
    """Part 3 and the knowledge collection read the edu-sharing repository; no base URL disables both."""
    if not settings.edu_sharing_base_url:
        log.warning("EDU_SHARING_BASE_URL is empty; collections are disabled")
        return None
    client = EduSharingClient(
        settings.edu_sharing_base_url,
        user=settings.edu_sharing_user,
        password=settings.edu_sharing_password,
        timeout_s=settings.edu_sharing_timeout_s,
    )
    if settings.edu_sharing_user and not settings.api_key_list:
        # Every collection a caller names is read with these credentials, and the cache hands the result to all
        log.warning(
            "EDU_SHARING_USER is set but API_KEYS is not: every caller reads what that account may read in the "
            "repository, collections that are not public and the texts of their materials included (audit SE-06)"
        )
    options = CollectionOptions(
        ttl_s=settings.collection_cache_ttl_s,
        overview=OverviewOptions(max_items=settings.collection_max_items or None),
        knowledge=KnowledgeOptions(
            max_materials=settings.knowledge_max_materials,
            max_chars=settings.knowledge_max_chars,
            concurrency=settings.knowledge_concurrency,
            text_ttl_s=settings.material_text_cache_ttl_s,
        ),
    )
    cache: TtlCache | None = None
    try:
        cache = TtlCache(settings.wlo_cache_path)
    except (sqlite3.Error, OSError) as exc:  # the cache only saves time; the repository still answers
        log.warning(
            "repository cache unavailable at %s (%s); every read goes to the repository", settings.wlo_cache_path, exc
        )
    return CollectionBuilder(client=client, cache=cache, options=options)


def build_curricula(settings: Settings) -> CurriculaBuilder:
    """Part 2 reads the harvested MEM cache in STATE_DIR; without it the part renders a hint."""
    subjects_path = settings.subjects_path
    if subjects_path.exists():
        subjects = SubjectCatalog.load(subjects_path)
    else:
        log.warning("subject mapping not found at %s; part 2 searches all subjects", subjects_path)
        subjects = SubjectCatalog.empty()
    return CurriculaBuilder(
        store=LehrplanStore(settings.lehrplan_db_path),
        subjects=subjects,
        options=RenderOptions(max_groups_per_land=settings.lehrplan_max_groups_per_land or None),
    )


def close_clients(app: FastAPI) -> None:
    """Close the outbound HTTP clients (Kiwix catalog, edu-sharing, b-api) when the process shuts down."""
    service = getattr(app.state, "service", None)
    if service is not None:
        service.close()  # the clients of other repositories a node was read from (D45)
    collections = getattr(app.state, "collections", None)
    llm = getattr(app.state, "llm", None)
    for client in (
        getattr(app.state, "catalog", None),
        collections.client if collections is not None else None,
        llm.client if llm is not None else None,
    ):
        if client is not None:
            client.close()


def close_indexes(app: FastAPI) -> None:
    """Close the Wikidata and the GND index, which hold a connection each for the life of the worker (audit
    2026-09-29, S1: the lifespan closed only the HTTP clients)."""
    for index in (getattr(app.state, "wikidata", None), getattr(app.state, "gnd", None)):
        if index is not None:
            index.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    close_clients(app)
    close_indexes(app)


# D33, D53 and D57 removed these; unknown names are ignored, so a stale value would change nothing without a word
REMOVED_SETTINGS = ("LLM_MODE_DEFAULT", "LLM_ROUTER_ENABLED", "LLM_ROUTER_MAX_CHUNKS")
REMOVED_DEFAULTS = (
    "MATCHER_DEFAULT",
    "LLM_ARTICLE_CHOICE_DEFAULT",
    "LLM_EXTRACTION_DEFAULT",
    "LLM_GENERATION_DEFAULT",
    "LLM_ENRICHMENT_DEFAULT",
)
REMOVED_QA_MODELS = ("QG_MODEL_PATH", "QA_MODEL_PATH")


def warn_about_removed_settings() -> None:
    """Name settings of the environment that no longer do anything (only the process environment is visible here)."""
    stale = [name for name in REMOVED_SETTINGS if os.environ.get(name)]
    if stale:
        log.warning(
            "%s no longer exist (D33): part 1 follows the profile (PRESET_DEFAULT)",
            ", ".join(stale),
        )
    defaults = [name for name in REMOVED_DEFAULTS if os.environ.get(name)]
    if defaults:
        log.warning("%s no longer exist (D53): the profile decides (PRESET_DEFAULT)", ", ".join(defaults))
    models = [name for name in REMOVED_QA_MODELS if os.environ.get(name)]
    if models:
        log.warning("%s no longer exist (D57): /api/v2/qa asks with the rules or the LLM", ", ".join(models))


def describe_matching(settings: Settings) -> dict[str, Any]:
    """What the matcher really consists of, decided once at start; /health reports it.

    A Model2Vec model that is configured but does not load leaves the matcher weaker without saying so. The
    check happens here, so the answer costs nothing per request and the model is loaded before the first one.
    """
    components = active_components(LOCAL_MATCHER, settings.model2vec_path)
    if not settings.model2vec_path:  # empty is a choice; an entry emptied in a panel overrides the image's model (S5)
        log.warning(
            "MODEL2VEC_PATH is empty: hybrid_light matches without embeddings and finds less; an empty entry also "
            "switches off the model the image brings - leave the line out to keep it"
        )
    elif "model2vec" not in components:
        log.error(
            "MODEL2VEC_PATH=%s holds no usable model; the matcher runs without embeddings and finds less",
            settings.model2vec_path,
        )
    return {
        "matcher": LOCAL_MATCHER,
        "components": components,
        "embeddings": "model2vec" in components,
    }


def describe_entities(settings: Settings) -> dict[str, Any]:
    """Whether the recognition model is there, decided once at start; /health reports it with the Wikidata index.

    The model is optional: without it /api/v2/entities answers with the terms of the archives alone. That is a
    weaker answer, not an error, so it has to be visible rather than silent. The index is read at every /health
    call instead (``app.api.health``): the sync builds or replaces it while the service runs (D64).
    """
    ready = load_spacy(settings.spacy_model) is not None
    if not settings.spacy_model:  # empty is a choice; an entry emptied in a panel overrides the image's model (S5)
        log.warning(
            "SPACY_MODEL is empty: /api/v2/entities finds only the terms of the archives (no ner), and the QA rules "
            "fall back to four templates; an empty entry also switches off the model the image brings - leave the "
            "line out to keep it"
        )
    elif not ready:
        log.error("SPACY_MODEL=%r is not usable; entity recognition runs without it", settings.spacy_model)
    return {"ner": ready, "model": settings.spacy_model}


def route_template(routes: Sequence[BaseRoute], scope: Scope) -> str:
    """The template of the route a request was meant for, when it left none in its scope - the metric's label.

    The 413 of BodySizeLimit answers a declared length before the router runs and counted as unmatched, beside the
    404s (audit 2026-09-29, S8); /docs, /redoc and /openapi.json are plain Starlette routes, which never store one. The
    templates are a fixed set, so the label values stay bounded; a path no route takes stays unmatched.
    """
    for context in iter_route_contexts(routes):  # the routes of the included routers as well (FastAPI 0.141)
        match, _ = context.matches(scope)
        if match is not Match.NONE:
            return context.path or UNMATCHED_ROUTE
    return UNMATCHED_ROUTE


def log_defaults(settings: Settings, service: CompendiumService, templates: TemplateManager) -> None:
    """What a request that names no profile or template gets (D68): the profile follows the LLM, and a TEMPLATE_DEFAULT
    that names no template leaves the shipped one until a template of that id exists."""
    log.info(
        "a request without preset runs %s, without template_id %s", service.default_preset, settings.template_default
    )
    if service.default_preset != settings.preset_default:
        log.info(
            "PRESET_DEFAULT=%s applies once an LLM is configured (LLM_ENABLED, B_API_KEY)", settings.preset_default
        )
    try:
        templates.get(settings.template_default)
    except TemplateNotFoundError:
        log.warning(
            "TEMPLATE_DEFAULT=%s names no template: a request without template_id takes %s until one of that id "
            "exists (GET /api/v2/templates lists them)",
            settings.template_default,
            SHIPPED_DEFAULT,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application; nothing happens at import time."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    warn_about_removed_settings()
    registry = build_registry(settings)
    templates = TemplateManager(custom_dir=Path(settings.state_dir) / "templates")
    service = build_service(settings, registry, templates)
    if not registry.ready:
        log.warning(
            "no ZIM archives found (ZIM_PATHS=%r, ZIM_DIR=%s); /ready will report 503",
            settings.zim_paths,
            settings.zim_dir,
        )
    else:
        log.info("archives loaded: %s", ", ".join(a.file_name for a in registry.archives))
    log_defaults(settings, service, templates)

    app = FastAPI(
        title="Kompendium-API v2",
        version=__version__,
        description=(
            "Kompendiale Texte aus Kiwix-ZIM-Wissen, Lehrplanbezügen und Sammlungsmetadaten. Fünf Profile (preset) "
            "legen fest, wo ein LLM mitarbeitet: llm-free nie, balanced bei der Wahl der Artikel eines Themas "
            "(Übersicht und Teile, unsichere Artikel) und beim Erkennen von Entitäten, best-quality zusätzlich bei "
            "der Zuordnung der Absätze und der Prüfung der Lehrplanelemente "
            "und bei mehrdeutigen Wörtern, best-quality-generated "
            "schreibt zudem den Text, best-coverage-generated schreibt jeden Baustein vollständig zum angefragten "
            "Thema, wo die Quellen nichts dazu sagen aus Modellwissen. Ohne preset gilt das Profil des Servers "
            "(PRESET_DEFAULT, ausgeliefert balanced, auf einem Server ohne LLM llm-free). "
            "Jeder Endpunkt sagt, was die Profile dort bewirken, und seine Beispiele reichen von der kürzesten Anfrage "
            "bis zu einer mit allen Parametern. Was ein LLM beigetragen hat, sagt die Antwort. Fehler kommen als "
            "Status, nie als Text mit HTTP 200. Mit UI_ENABLED zeigt der Server unter /ui/ eine Prüfansicht, auf der "
            "Menschen die Antworten ohne Kenntnis der API prüfen."
        ),
        lifespan=lifespan,
        default_response_class=JsonResponse,
        dependencies=[Depends(name_the_route)],
        docs_url=None,  # /docs and /redoc with a policy of their own below (audit 2026-09-29, S12)
        redoc_url=None,
        openapi_url=OPENAPI_PATH if settings.api_docs_enabled else None,
    )
    app.state.settings = settings
    listen_to_calls(record_llm_call)  # every LLM call, by route and outcome (BE-04)
    app.state.registry = registry
    app.state.templates = templates
    app.state.service = service
    app.state.curricula = service.curricula
    app.state.collections = service.collections
    app.state.llm = service.llm
    manifest = load_subscriptions(settings)
    app.state.manifest = manifest
    app.state.required_ids = resolve_required_ids(settings, manifest)
    app.state.catalog = KiwixCatalog(settings.zim_catalog_url or OPDS_DEFAULT_URL)
    app.state.matching = describe_matching(settings)
    app.state.wikidata = WikidataIndex(settings.wikidata_db_path)
    app.state.gnd = GndIndex(settings.gnd_db_path)
    app.state.entities = describe_entities(settings)
    app.state.rate_limiter = RateLimiter(settings.rate_limit) if settings.rate_limit > 0 else None
    app.state.system_limiter = system_limiter()
    app.include_router(health_router)
    app.include_router(v2_router)
    app.include_router(v2_admin_router)
    app.include_router(knowledge_router)
    app.include_router(entities_router)
    app.include_router(nodes_router)
    app.include_router(qa_router)
    app.include_router(matching_router)
    app.include_router(zim_router)
    app.include_router(zim_admin_router)
    app.include_router(lehrplan_router)
    app.include_router(lehrplan_admin_router)
    app.include_router(collections_router)
    if settings.metrics_enabled:
        app.include_router(metrics_router)
    if settings.api_docs_enabled:
        app.include_router(docs_router(OPENAPI_PATH, app.title))
    if settings.ui_enabled:
        app.include_router(ui_router())
        if not settings.api_key_list:
            # The page asks every endpoint for whoever opens it; a test server ran just so, in public
            log.warning(
                "UI_ENABLED is set but API_KEYS is not: anyone who reaches /ui/ calls every endpoint through it, and "
                "the profiles with an LLM spend b-api tokens for all callers (audit 2026-09-29, S2)"
            )
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    for error, answer in DOMAIN_ERRORS.items():
        app.add_exception_handler(error, answer)
    # Added first, so it runs innermost: the refusal of a body too large still gets its request id and its metric
    app.add_middleware(BodySizeLimit, max_bytes=settings.request_body_max_bytes)

    if not settings.zim_path_list:
        refresher = RegistryRefresher(registry, settings.zim_dir)

        @app.middleware("http")
        async def follow_active_archives(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            # One stat call per request; archives are reopened only when the sync job replaced active.json. It runs
            # in the monitoring threads, so a probe never waits for a thread that a compendium request holds.
            await run_system(request, refresher.refresh)
            return await call_next(request)

    @app.middleware("http")
    async def record_http_metrics(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Added last, so it runs outermost and times the whole request; scrapes are not requests of the service.
        if request.url.path == METRICS_PATH:
            return await call_next(request)
        started = time.perf_counter()
        status = 500  # an exception escaping the app reaches the client as a 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # FastAPI stores the matched route in the scope; its template keeps the label values bounded
            route = getattr(request.scope.get("route"), "path", None) or route_template(app.routes, request.scope)
            observe_request(request.method, route, status, time.perf_counter() - started)

    @app.middleware("http")
    async def name_the_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Added last, so it runs outermost: every log line of this request, and the answer, carry the same id
        request_id = set_request_id(request.headers.get(REQUEST_ID_HEADER))
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.exception_handler(Exception)
    async def report_unexpected(request: Request, exc: Exception) -> JsonResponse:
        """An error nobody planned for: the log holds the cause, the caller gets the id to quote (audit OPS-03)."""
        request_id = current_request_id()
        log.exception("unhandled error in %s %s (request %s)", request.method, request.url.path, request_id)
        return JsonResponse(
            status_code=500,
            content={"detail": "Interner Fehler; bitte die Anfrage-ID melden", "request_id": request_id},
            headers={REQUEST_ID_HEADER: request_id},
        )

    return app
