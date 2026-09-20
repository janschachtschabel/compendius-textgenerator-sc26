"""Central configuration (environment variables or .env). See PLAN.md, section 3.5."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.requests import Extraction, Generation

Provider = Literal["openai", "academiccloud"]
FacetsLevel = Literal["minimal", "full"]
ZimProfile = Literal["compact", "standard", "extended"]


# Which b-api belongs to which edu-sharing repository (hosts reachable on 2026-09-20). A service that reads
# staging collections must not quietly ask the production model, so the b-api follows the repository unless
# B_API_BASE_URL says otherwise. An installation outside these two names sets both addresses itself.
B_API_BY_REPOSITORY = {
    "repository.staging.openeduhub.net": "https://b-api.staging.openeduhub.net",
    "redaktion.openeduhub.net": "https://b-api.prod.openeduhub.net",
}


def b_api_for(repository_url: str) -> str:
    """The b-api belonging to this repository, or "" when the host is not one of the known environments."""
    return B_API_BY_REPOSITORY.get(urlparse(repository_url).hostname or "", "")


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    """Project-wide settings, loaded once (see ``get_settings``)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    log_level: str = Field("INFO", description="Python log level name")

    # --- ZIM archives ------------------------------------------------------------------------
    zim_dir: Path = Field(Path("data/zim"), description="Directory with ZIM archives and active.json")
    zim_profile: ZimProfile = Field("standard", description="Subscription profile from config/zim_subscriptions.yaml")
    zim_required: str = Field(
        "",
        description="Comma separated archive ids that must be present before the service reports ready; "
        "empty derives them from the manifest for ZIM_PROFILE",
    )
    zim_paths: str = Field(
        "",
        description="Comma separated explicit ZIM paths (development and tests). Overrides ZIM_DIR discovery.",
    )
    zim_bootstrap_download: bool = Field(False, description="Sync job downloads missing required archives")
    zim_sync_interval: str = Field("30d", description="Catalog check interval of `compendium zim sync --loop`")
    zim_catalog_url: str = Field("", description="Kiwix OPDS entries URL; empty uses the built-in default")
    zim_download_hosts: str = Field(
        "download.kiwix.org,lb.download.kiwix.org,mirror.download.kiwix.org",
        description="Hosts a download may start from (redirects to mirrors are hash-verified)",
    )
    zim_retention_hours: int = Field(24, ge=0, description="Grace period before a replaced archive is deleted")

    # --- State, templates, matching ------------------------------------------------------------
    state_dir: Path = Field(Path("data/state"), description="SQLite databases, custom templates")
    config_dir: Path = Field(Path("config"), description="facets.yaml, heading_lexicon.yaml, ...")
    template_default: str = Field("sc26", description="Default template id")
    matcher_default: str = Field("hybrid_light", description="Default slot matching strategy")
    policy_confident_score: float = Field(
        0.65,
        ge=0.0,
        le=1.0,
        description="Fused score from which a ranker hit counts; below it the default slot applies",
    )
    policy_section_smoothing: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="Weight of a section's mean score in every paragraph's score; 0 switches the smoothing off",
    )
    facets_level: FacetsLevel = Field("minimal", description="minimal or full facet annotation in part 1")
    facets_visible: bool = Field(False, description="Render visible [Facette: Wert] labels in Markdown")
    corpus_max_articles: int = Field(12, ge=1, le=50, description="Maximum articles per compendium corpus")
    corpus_max_chunks: int = Field(400, ge=20, le=5000, description="Maximum chunks per compendium corpus")
    model2vec_path: str = Field("", description="Local Model2Vec model path; empty disables the embedding matcher")
    eval_gold_dir: Path = Field(Path("eval/gold"), description="Gold standard files for eval run and matching/compare")

    # --- Curricula: MEM cache for part 2 (PLAN.md 5, decision D16) -----------------------------
    lehrplan_endpoint: str = Field(
        "https://sparql.mem.edufeed.org/sparql/", description="MEM SPARQL endpoint, used by the harvest only"
    )
    lehrplan_check_interval: str = Field("7d", description="Harvest loop: compare curriculum counts with MEM")
    lehrplan_harvest_max_age: str = Field("30d", description="Full harvest at the latest after this cache age")
    lehrplan_request_pause_s: float = Field(0.5, ge=0.0, description="Pause between SPARQL requests during a harvest")
    lehrplan_max_groups_per_land: int = Field(
        0, ge=0, description="Optional cap of part 2: Lernbereiche per state and level; 0 renders every match (D23)"
    )

    # --- Collections: edu-sharing repository for part 3 and the knowledge collection (PLAN.md 6) ---
    edu_sharing_base_url: str = Field(
        "https://repository.staging.openeduhub.net/edu-sharing/rest",
        description="REST root of the edu-sharing repository; empty disables collections",
    )
    edu_sharing_user: str = Field("", description="Optional Basic-Auth user; anonymous reads otherwise")
    edu_sharing_password: str = Field("", description="Optional Basic-Auth password")
    edu_sharing_timeout_s: float = Field(30.0, ge=1.0, description="Timeout per repository request")
    collection_cache_ttl_s: int = Field(3600, ge=0, description="Cache of collection metadata and listings")
    collection_max_items: int = Field(0, ge=0, description="Optional cap of listed materials per list; 0 = all (D23)")
    material_text_cache_ttl_s: int = Field(7 * 86_400, ge=0, description="Cache of extracted material texts")
    knowledge_max_materials: int = Field(30, ge=1, le=200, description="Materials read for the knowledge collection")
    knowledge_max_chars: int = Field(20_000, ge=500, description="Characters kept per material text")
    knowledge_concurrency: int = Field(4, ge=1, le=8, description="Parallel text fetches from the repository")

    # --- LLM (optional, via b-api) -------------------------------------------------------------
    llm_enabled: bool = Field(False, description="Enable b-api usage at all")
    llm_extraction_default: Extraction = Field("rule-based", description="Default of the extraction switch")
    llm_extraction_candidates: int = Field(
        8, ge=1, le=20, description="Paragraphs offered per block with extraction=llm (rule-based choice first)"
    )
    llm_generation_default: Generation = Field("rule-based", description="Default of the generation switch")
    llm_fast_sections: str = Field("sc26_1,sc26_11", description="Slots the LLM writes with generation=llm-fast")
    b_api_key: str = Field("", description="b-api key, sent as X-API-KEY header")
    b_api_base_url: str = Field(
        "", description="b-api host, no path; empty takes the one belonging to EDU_SHARING_BASE_URL"
    )
    b_api_provider: Provider = Field("openai", description="b-api provider: openai or academiccloud")
    b_api_model: str = Field("gpt-5.6-luna", description="Model id at the selected provider")
    llm_timeout_s: int = Field(120, ge=10, description="Timeout per LLM request")
    llm_max_concurrency: int = Field(4, ge=1, le=26, description="Parallel LLM requests")
    llm_attempts: int = Field(
        3, ge=1, le=6, description="Attempts per LLM request (429/502/503/504, connection errors)"
    )
    llm_reasoning_effort: str = Field("low", description="GPT-5 and o-series models: reasoning_effort (D25)")
    llm_verbosity: str = Field("low", description="GPT-5 series models: verbosity (D25)")
    llm_temperature: float = Field(0.2, ge=0.0, le=2.0, description="Classic models only (GPT-5 rejects it)")
    llm_max_tokens_per_request: int = Field(
        60_000,
        ge=100,
        description="Budget guard per compendium request; both switches on llm spend up to about 37,000 tokens (D33)",
    )
    llm_daily_token_budget: int = Field(
        2_000_000, ge=0, description="Daily token cap of all workers together (llm_budget.db in STATE_DIR)"
    )
    llm_unsupported_sentences: Literal["drop", "mark"] = Field(
        "drop",
        description="LLM sentences without a valid, covering citation: drop them, or keep them marked as conclusions",
    )

    # --- Service -------------------------------------------------------------------------------
    request_timeout_s: int = Field(
        120,
        ge=5,
        description="Time budget per compendium request for LLM calls and material reads of the knowledge collection",
    )
    rate_limit: int = Field(
        60, ge=0, description="Requests per minute and client on the generating endpoints (per worker); 0 = off"
    )
    admin_token: str = Field("", description="Token for admin endpoints; empty disables them")
    api_docs_enabled: bool = Field(True, description="Serve /docs, /redoc and /openapi.json")
    metrics_enabled: bool = Field(True, description="Serve GET /metrics for Prometheus")
    metrics_token: str = Field("", description="Bearer token GET /metrics requires; empty = no token")

    @property
    def b_api_url(self) -> str:
        """The b-api to call: the configured one, otherwise the one belonging to the repository."""
        return self.b_api_base_url or b_api_for(self.edu_sharing_base_url)

    @property
    def zim_required_ids(self) -> list[str]:
        return _split_csv(self.zim_required)

    @property
    def zim_path_list(self) -> list[Path]:
        return [Path(p) for p in _split_csv(self.zim_paths)]

    @property
    def zim_download_host_list(self) -> list[str]:
        return _split_csv(self.zim_download_hosts)

    @property
    def zim_manifest_path(self) -> Path:
        return Path(self.config_dir) / "zim_subscriptions.yaml"

    @property
    def lehrplan_db_path(self) -> Path:
        return Path(self.state_dir) / "lehrplan.db"

    @property
    def subjects_path(self) -> Path:
        return Path(self.config_dir) / "subjects.yaml"

    @property
    def wlo_cache_path(self) -> Path:
        return Path(self.state_dir) / "wlo_cache.db"

    @property
    def llm_budget_path(self) -> Path:
        return Path(self.state_dir) / "llm_budget.db"

    @property
    def llm_fast_section_ids(self) -> list[str]:
        return _split_csv(self.llm_fast_sections)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
