"""FastAPI application factory. Start with ``uvicorn app.main:create_app --factory``."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.routing import Route

from app import __version__
from app.api.health import router as health_router
from app.api.limits import RateLimiter
from app.api.metrics import METRICS_PATH
from app.api.metrics import router as metrics_router
from app.api.system_threads import run_system, system_limiter
from app.api.v1.linker import router as v1_linker_router
from app.api.v1.qa import router as v1_qa_router
from app.api.v1.routes import router as v1_router
from app.api.v1.utils import router as v1_utils_router
from app.api.v2.collections import router as collections_router
from app.api.v2.lehrplan import admin as lehrplan_admin_router
from app.api.v2.lehrplan import router as lehrplan_router
from app.api.v2.matching import admin as matching_admin_router
from app.api.v2.matching import router as matching_router
from app.api.v2.routes import router as v2_router
from app.api.v2.zim import admin as zim_admin_router
from app.api.v2.zim import router as zim_router
from app.llm.budget import DailyStore, TokenBudget
from app.llm.budget_store import SqliteDailyStore
from app.llm.client import BApiClient
from app.llm.gateway import LlmGateway, LlmOptions
from app.logging import REQUEST_ID_HEADER, configure_logging, current_request_id, set_request_id
from app.matching.lexicon import HeadingLexicon
from app.matching.registry import STRATEGIES, active_components
from app.observability.metrics import UNMATCHED_ROUTE, observe_request
from app.service import CompendiumService
from app.settings import Settings, b_api_for, get_settings
from app.sources.lehrplan.part import CurriculaBuilder
from app.sources.lehrplan.render import RenderOptions
from app.sources.lehrplan.store import LehrplanStore
from app.sources.lehrplan.subjects import SubjectCatalog
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
from app.templates.manager import TemplateManager

log = logging.getLogger(__name__)


def build_registry(settings: Settings) -> ZimRegistry:
    """Explicit ZIM_PATHS win (development, tests); otherwise active.json in ZIM_DIR decides."""
    if settings.zim_path_list:
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
    collections = getattr(app.state, "collections", None)
    llm = getattr(app.state, "llm", None)
    for client in (
        getattr(app.state, "catalog", None),
        collections.client if collections is not None else None,
        llm.client if llm is not None else None,
    ):
        if client is not None:
            client.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    close_clients(app)


# D33 replaced these; unknown names are ignored, so a stale value would change nothing without a word
REMOVED_SETTINGS = ("LLM_MODE_DEFAULT", "LLM_ROUTER_ENABLED", "LLM_ROUTER_MAX_CHUNKS")


def warn_about_removed_settings() -> None:
    """Name settings of the environment that no longer do anything (only the process environment is visible here)."""
    stale = [name for name in REMOVED_SETTINGS if os.environ.get(name)]
    if stale:
        log.warning(
            "%s no longer exist (D33): part 1 follows LLM_EXTRACTION_DEFAULT and LLM_GENERATION_DEFAULT",
            ", ".join(stale),
        )


def describe_matching(settings: Settings) -> dict[str, Any]:
    """What the matcher really consists of, decided once at start; /health reports it.

    A Model2Vec model that is configured but does not load leaves the matcher weaker without saying so. The
    check happens here, so the answer costs nothing per request and the model is loaded before the first one.
    """
    if settings.matcher_default not in STRATEGIES:
        log.warning("MATCHER_DEFAULT=%r is not a known strategy", settings.matcher_default)
        return {"matcher": settings.matcher_default, "components": [], "embeddings": False}
    components = active_components(settings.matcher_default, settings.model2vec_path)
    if settings.model2vec_path and "model2vec" not in components:
        log.error(
            "MODEL2VEC_PATH=%s holds no usable model; the matcher runs without embeddings and finds less",
            settings.model2vec_path,
        )
    return {
        "matcher": settings.matcher_default,
        "components": components,
        "embeddings": "model2vec" in components,
    }


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

    app = FastAPI(
        title="Kompendium-API v2",
        version=__version__,
        description=(
            "Kompendiale Texte aus Kiwix-ZIM-Wissen, Lehrplanbezügen und Sammlungsmetadaten. "
            "`/api/v2` ist der Vertrag des Neubaus, `/api/v1` der des alten Dienstes auf derselben Maschinerie "
            "(Unterschiede in MIGRATION.md). Fehler kommen als Status, nie als Text mit HTTP 200."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )
    app.state.settings = settings
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
    app.state.rate_limiter = RateLimiter(settings.rate_limit) if settings.rate_limit > 0 else None
    app.state.system_limiter = system_limiter()
    app.include_router(health_router)
    app.include_router(v1_router)  # the contract of the old service (8.1)
    app.include_router(v1_linker_router)
    app.include_router(v1_qa_router)
    app.include_router(v1_utils_router)
    app.include_router(v2_router)
    app.include_router(matching_router)
    app.include_router(matching_admin_router)
    app.include_router(zim_router)
    app.include_router(zim_admin_router)
    app.include_router(lehrplan_router)
    app.include_router(lehrplan_admin_router)
    app.include_router(collections_router)
    if settings.metrics_enabled:
        app.include_router(metrics_router)

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

    # /docs, /redoc and /openapi.json are plain Starlette routes, which leave no route in the scope; their paths
    # are a fixed set, so they may serve as labels
    plain_paths = frozenset(r.path for r in app.routes if isinstance(r, Route) and not isinstance(r, APIRoute))

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
            route = getattr(request.scope.get("route"), "path", None)
            if route is None:
                route = request.url.path if request.url.path in plain_paths else UNMATCHED_ROUTE
            observe_request(request.method, route, status, time.perf_counter() - started)

    @app.middleware("http")
    async def name_the_request(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Added last, so it runs outermost: every log line of this request, and the answer, carry the same id
        request_id = set_request_id(request.headers.get(REQUEST_ID_HEADER))
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.exception_handler(Exception)
    async def report_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """An error nobody planned for: the log holds the cause, the caller gets the id to quote (audit OPS-03)."""
        request_id = current_request_id()
        log.exception("unhandled error in %s %s (request %s)", request.method, request.url.path, request_id)
        return JSONResponse(
            status_code=500,
            content={"detail": "Interner Fehler; bitte die Anfrage-ID melden", "request_id": request_id},
            headers={REQUEST_ID_HEADER: request_id},
        )

    return app
