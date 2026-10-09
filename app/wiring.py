"""How the service is built from its settings: the archives, the service with part 2 and part 3, the LLM gateway
(audit 2026-09-18, A-03).

The web entry app/main.py, the CLI and the sync and harvest sidecars build it the same way. The module loads neither
FastAPI nor the API's metrics, so the sidecars, which must not create them, import it like any other.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app.compendium.gateway import LlmGateway, LlmOptions
from app.knowledge.lexicon import HeadingLexicon
from app.llm.budget import DailyStore, TokenBudget
from app.llm.budget_store import SqliteDailyStore
from app.llm.client import BApiClient, is_reasoning_model, needs_thinking_off
from app.llm.deadline import MIN_CALL_S
from app.llm.prompts import PROMPTS
from app.llm.routing import ROUTER
from app.service import CompendiumService
from app.settings import PROVIDER_REQUEST_TIMEOUT_S, Settings, b_api_for, parse_reasoning_efforts
from app.sources.lehrplan.part import CurriculaBuilder
from app.sources.lehrplan.render import RenderOptions
from app.sources.lehrplan.store import LehrplanStore
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.knowledge import KnowledgeOptions
from app.sources.wlo.overview import OverviewOptions
from app.sources.wlo.part import CollectionBuilder, CollectionOptions
from app.sources.zim.registry import ZimRegistry
from app.sources.zim.subscriptions import SubscriptionManifest, load_manifest
from app.synthesis.facets import FacetCatalog
from app.templates.manager import TemplateManager

log = logging.getLogger(__name__)

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


def _parameters_of(model: str) -> tuple[bool, bool]:
    """What decides the parameters the service sends a model (``BApiClient._body``)."""
    return is_reasoning_model(model), needs_thinking_off(model)


def warn_about_llm_settings(settings: Settings) -> None:
    """Settings the LLM can hardly work with, named at start; the service keeps them (a warning, not a refusal: a
    stricter check stopped all containers on 2026-09-28, BE-13)."""
    if settings.request_time_limit_s <= SHORTEST_LLM_TIMEOUT_S:
        log.warning(
            "REQUEST_TIMEOUT_S=%d leaves the LLM hardly a call: one starts only while %g s of the request remain and "
            "has to be answered by its end, and the quickest LLM steps take about 4 s, the matching and the writing "
            "longer; the LLM steps fall back to the rules. Empty, it is the provider's default, %d s here (audit "
            "2026-09-29, S6)",
            settings.request_time_limit_s,
            MIN_CALL_S,
            PROVIDER_REQUEST_TIMEOUT_S[settings.b_api_provider],
        )
    if settings.b_api_route and settings.b_api_provider != ROUTER:
        log.warning(
            "B_API_ROUTE=%r has no effect: only B_API_PROVIDER=router sends a route, to the b-api's router (D97)",
            settings.b_api_route,
        )
    route = settings.b_api_route_name
    if "/" in route and _parameters_of(route) != _parameters_of(settings.b_api_model):
        log.warning(
            "B_API_ROUTE=%r names a model of another parameter family than B_API_MODEL=%s: the service sends it the "
            "parameters of B_API_MODEL, which it refuses with a 400 on every call; B_API_MODEL names the family (D97)",
            route,
            settings.b_api_model,
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
    efforts, malformed = parse_reasoning_efforts(settings.llm_reasoning_efforts)
    problems = [f"{entry!r} is not prompt=effort" for entry in malformed]
    problems += [f"{name} is no question of the service" for name in efforts if name not in PROMPTS]
    problems += [
        f"{effort!r} for {name} is not one of {', '.join(REASONING_EFFORTS)}"
        for name, effort in efforts.items()
        if name in PROMPTS and effort not in REASONING_EFFORTS
    ]
    if problems:
        log.warning(
            "LLM_REASONING_EFFORTS: %s - a question the service does not ask never gets its effort, and %s may refuse "
            "an effort it does not know with a 400 (M59)",
            "; ".join(problems),
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
        route=settings.b_api_route,
        timeout_s=settings.llm_timeout_s,
        max_concurrency=settings.llm_concurrency,
        attempts=settings.llm_attempts,
        reasoning_effort=settings.llm_reasoning_effort,
        reasoning_efforts=settings.llm_reasoning_effort_by_prompt,
        verbosity=settings.llm_verbosity,
        temperature=settings.llm_temperature,
        response_cache=settings.b_api_response_cache,
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
        concurrency=settings.llm_concurrency,
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
        generic_hits=settings.lehrplan_generic_word_hits,
    )
