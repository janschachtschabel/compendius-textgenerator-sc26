"""FastAPI application factory. Start with ``uvicorn app.main:create_app --factory``."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app import __version__
from app.api.active_archives import FollowActiveArchives
from app.api.body_limit import BodySizeLimit
from app.api.docs import docs_router
from app.api.domain_errors import DOMAIN_ERRORS
from app.api.errors import JsonResponse, http_error, validation_error
from app.api.health import router as health_router
from app.api.limits import RateLimiter
from app.api.metrics import name_the_route
from app.api.metrics import router as metrics_router
from app.api.request_log import RequestLog
from app.api.system_threads import system_limiter
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
from app.knowledge.recognise import load_spacy
from app.llm.call import listen_to_calls
from app.logging import configure_logging
from app.matching.registry import LOCAL_MATCHER, active_components
from app.observability.metrics import record_llm_call
from app.service import CompendiumService
from app.settings import Settings, get_settings
from app.sources.gnd.index import GndIndex
from app.sources.wikidata.index import WikidataIndex
from app.sources.zim.catalog import OPDS_DEFAULT_URL, KiwixCatalog
from app.sources.zim.refresh import RegistryRefresher
from app.templates.manager import SHIPPED_DEFAULT, TemplateManager, TemplateNotFoundError
from app.ui.routes import ui_router
from app.wiring import build_registry, build_service, load_subscriptions, resolve_required_ids

log = logging.getLogger(__name__)

OPENAPI_PATH = "/openapi.json"


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
    configure_logging(settings.log_level, settings.log_format)
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
            "(PRESET_DEFAULT, ausgeliefert best-quality-generated, auf einem Server ohne LLM llm-free). "
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
        app.add_middleware(FollowActiveArchives, refresher=RegistryRefresher(registry, settings.zim_dir))
    # Added last, so it runs outermost: it names the request, times all of it, and answers an error nothing else
    # handled (app/api/request_log.py)
    app.add_middleware(RequestLog, routes=app.routes)

    return app
