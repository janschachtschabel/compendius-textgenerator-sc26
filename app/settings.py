"""Central configuration (environment variables or .env). See PLAN.md, section 3.5."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.requests import Preset

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


# Admin and metrics tokens and the API keys: a token of one character was accepted (audit 2026-09-27, SE-08). The
# minimum is 16 characters (Jan, 2026-09-28; the audit asked for 32): generated, that is 64 bits and more, out of
# reach of guessing under the rate limit, and it keeps an invented word like "geheim12" out. Longer stays welcome.
MIN_SECRET_CHARS = 16

# The model the service asks when B_API_MODEL names none (D44)
DEFAULT_B_API_MODEL = "gpt-6-luna"
# The questions that think otherwise than LLM_REASONING_EFFORT (M59): without the model's thinking these chose the same
# articles, rated the curriculum elements alike and wrote equal topics and question pairs, in about half the time; the
# writing, the paragraph assignment, the entities and the article of a material lost without it and keep thinking
DEFAULT_REASONING_EFFORTS = (
    "topic_articles=none,article_choice=none,curriculum_check=none,topic_wording=none,qa_pairs=none"
)
# The settings whose empty value is documented as a choice of its own: no collections, only the configured repository,
# no embeddings, no spaCy model. Every other setting left empty is its default (BE-13). The image sets the two models;
# an entry emptied in a panel overrides that and switches them off, which the start says (audit 2026-09-29, S5).
EMPTY_IS_A_CHOICE = frozenset({"edu_sharing_base_url", "edu_sharing_repositories", "model2vec_path", "spacy_model"})


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _blank(value: Any) -> bool:
    return isinstance(value, str) and not value.strip()


def parse_reasoning_efforts(value: str) -> tuple[dict[str, str], list[str]]:
    """LLM_REASONING_EFFORTS as prompt id -> effort, and the entries that are not prompt=effort."""
    efforts: dict[str, str] = {}
    malformed: list[str] = []
    for entry in _split_csv(value):
        name, sep, effort = (part.strip() for part in entry.partition("="))
        if sep and name and effort:
            efforts[name] = effort
        else:
            malformed.append(entry)
    return efforts, malformed


class Settings(BaseSettings):
    """Project-wide settings, loaded once (see ``get_settings``)."""

    # hide_input_in_errors: a setting the service refuses must not reach the log with its value - it may be a secret
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore", hide_input_in_errors=True
    )

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
    preset_default: Preset = Field(
        "best-quality-generated",
        description="Profile of a request that names none (D53, D82): llm-free, balanced, best-quality, "
        "best-quality-generated or best-coverage-generated (D69). Every profile but llm-free needs LLM_ENABLED and "
        "B_API_KEY: without them a request that names such a profile is a 503, and one that names none runs llm-free "
        "whatever this says (D68)",
    )
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
    spacy_model: str = Field(
        "",
        description="spaCy model for /api/v2/entities and the QA rules: installed name or path; empty disables the "
        "model-based recognition and leaves the terms of the archives, and the QA rules fall back to four templates",
    )
    eval_gold_dir: Path = Field(Path("eval/gold"), description="Gold standard files for compendium eval")

    # --- Wikidata index of /entities: title to Wikidata number from two dewiki dumps (D43, D64) ---------------
    wikidata_dumps_url: str = Field(
        "https://dumps.wikimedia.org", description="Where the Wikidata sync reads the dewiki dumps; a mirror works too"
    )
    wikidata_check_interval: str = Field(
        "1d", description="Wikidata sync loop: build a missing index, a newer one after a newer Wikipedia archive"
    )
    gnd_dumps_url: str = Field(
        "https://data.dnb.de/opendata", description="Where the GND sync reads the DNB's dumps and their checksums (D65)"
    )
    gnd_check_interval: str = Field("1d", description="GND sync loop: build a missing index, a newer one per release")

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
    lehrplan_generic_word_hits: int = Field(
        1000,
        ge=0,
        description="Part 2 leaves out a search word of a topic other than its title that stands in more curriculum "
        "elements of the whole cache: too general (M58); 0 searches every word",
    )

    # --- Collections: edu-sharing repository for part 3 and the knowledge collection (PLAN.md 6) ---
    edu_sharing_base_url: str = Field(
        "https://repository.staging.openeduhub.net/edu-sharing/rest",
        description="REST root of the edu-sharing repository; empty disables collections",
    )
    edu_sharing_repositories: str = Field(
        "repository.staging.openeduhub.net,redaktion.openeduhub.net",
        description="Comma separated hosts a request may name as repository of its node_id (D45), besides the "
        "configured one; over https, and nodes are read without credentials from every repository",
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
    llm_extraction_candidates: int = Field(
        8,
        ge=1,
        le=20,
        description="Paragraphs offered per block with extraction=llm: all the rules assigned, then the next best "
        "up to this number",
    )
    llm_fast_sections: str = Field("sc26_1,sc26_11", description="Slots the LLM writes with generation=llm-fast")
    b_api_key: str = Field("", description="b-api key, sent as X-API-KEY header")
    b_api_base_url: str = Field(
        "", description="b-api host, no path; empty takes the one belonging to EDU_SHARING_BASE_URL"
    )
    b_api_provider: Provider = Field("openai", description="b-api provider: openai or academiccloud")
    b_api_model: str = Field(
        DEFAULT_B_API_MODEL, description="Model id at the selected provider (D44); empty takes the default"
    )
    b_api_response_cache: bool = Field(
        False,
        description="Let the b-api answer a request it has seen word for word from its store (D70). Off: every call "
        "carries a safety_identifier of its own, so the answer is new; the provider's prompt cache stays in use",
    )
    llm_timeout_s: int = Field(120, ge=10, description="Timeout per LLM request")
    llm_max_concurrency: int = Field(10, ge=1, le=26, description="Parallel LLM requests")
    llm_attempts: int = Field(
        3, ge=1, le=6, description="Attempts per LLM request (429/502/503/504, connection errors)"
    )
    llm_reasoning_effort: str = Field(
        "low",
        description="Reasoning models (GPT-5, GPT-6, o-series): reasoning_effort of every question "
        "LLM_REASONING_EFFORTS does not name",
    )
    llm_reasoning_efforts: str = Field(
        DEFAULT_REASONING_EFFORTS,
        description="Reasoning models: the questions with a reasoning_effort of their own, as prompt=effort, comma "
        "separated; the shipped ones answered as well without thinking (M59)",
    )
    llm_verbosity: str = Field("low", description="Reasoning models (GPT-5, GPT-6, o-series): verbosity (D25)")
    llm_temperature: float = Field(0.2, ge=0.0, le=2.0, description="Classic models only (reasoning models reject it)")
    llm_max_tokens_per_request: int = Field(
        60_000,
        ge=100,
        description="Budget guard per request in the profiles llm-free and balanced - a compendium, or part 1 and "
        "the pairs of /qa together; both switches on llm spend up to about 37,000 tokens (D33)",
    )
    llm_max_tokens_per_request_best_quality: int = Field(
        180_000,
        ge=100,
        description="Budget guard per request in the profiles best-quality, best-quality-generated and "
        "best-coverage-generated (D59, D69): next to "
        "matcher llm their LLM checks the curriculum elements of part 2, 80 to 90 tokens each; 60,000 covered about "
        "400 of them (M32). On the widest topic, Demokratie with 382 paragraphs and 819 elements, a compendium with "
        "both parts took 137,398 tokens in best-quality and 152,197 in best-quality-generated (M33)",
    )
    llm_daily_token_budget: int = Field(
        0,
        ge=0,
        description="Daily token cap of all workers together (llm_budget.db in STATE_DIR); 0, the default, sets none "
        "- in operation the service may work through many entries a day (D67). The day's usage is counted either way",
    )
    llm_unsupported_sentences: Literal["drop", "mark"] = Field(
        "drop",
        description="LLM sentences without a valid, covering citation: drop them, or keep them marked as conclusions",
    )

    # --- Service -------------------------------------------------------------------------------
    request_timeout_s: int = Field(
        120,
        ge=5,
        description="Time budget per request - a compendium, or part 1 and the pairs of /qa together - for LLM "
        "calls and every repository read: the collection and node of the request, part 3, the knowledge collection",
    )
    rate_limit: int = Field(
        60, ge=0, description="Requests per minute and client on the generating endpoints (per worker); 0 = off"
    )
    request_body_max_bytes: int = Field(
        1_000_000,
        ge=10_000,
        description="Bound of a request body; a larger one is a 413 before it is read. POST /api/v2/compendium and "
        "PUT /api/v2/templates/{id} take up to 13,000,000 bytes (existing_markdown, a whole template)",
    )
    admin_token: str = Field("", description="Token for admin endpoints; empty disables them")
    api_keys: str = Field(
        "",
        description="Comma-separated keys; once set, every endpoint that works under a profile wants one of them "
        "in X-API-Key (401 otherwise). Empty: those endpoints answer everyone",
    )
    api_docs_enabled: bool = Field(True, description="Serve /docs, /redoc and /openapi.json")
    ui_enabled: bool = Field(
        False,
        description="Serve the review page at /ui/ (D66), where people check the answers of every endpoint in the "
        "browser. It calls the endpoints with the key its reader enters, so API_KEYS guards it as it guards them",
    )
    metrics_enabled: bool = Field(True, description="Serve GET /metrics for Prometheus")
    metrics_token: str = Field("", description="Bearer token GET /metrics requires; empty = no token")

    @field_validator("admin_token", "metrics_token", "api_keys")
    @classmethod
    def _long_enough(cls, value: str, info: ValidationInfo) -> str:
        secrets = _split_csv(value) if info.field_name == "api_keys" else [value] if value else []
        if any(len(secret) < MIN_SECRET_CHARS for secret in secrets):
            name = (info.field_name or "").upper()
            raise ValueError(
                f"{name} braucht mindestens {MIN_SECRET_CHARS} Zeichen je Wert, etwa aus openssl rand -hex 32"
            )
        return value

    @model_validator(mode="before")
    @classmethod
    def _empty_is_the_default(cls, data: Any) -> Any:
        # A panel or a .env writes an entry left blank as VAR=, and whoever enters nothing gets the default (Jan,
        # 2026-09-28). Read as "", 34 of 67 settings refused it and stopped all five containers, 20 took it for their
        # value (audit 2026-09-28, BE-13). Not env_ignore_empty: that falls through to the .env file, and a secret
        # compose empties for the sidecars would come back from there.
        if not isinstance(data, dict):
            return data
        # Blanks entered for a choice are that choice: kept, "   " was a repository address or a model name
        return {
            name: "" if _blank(value) else value
            for name, value in data.items()
            if name in EMPTY_IS_A_CHOICE or not _blank(value)
        }

    @property
    def api_key_list(self) -> list[str]:
        return _split_csv(self.api_keys)

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
    def edu_sharing_allowed_hosts(self) -> frozenset[str]:
        """Hosts a request may name as repository: the allowlist and the configured repository (D45)."""
        configured = urlparse(self.edu_sharing_base_url).hostname if self.edu_sharing_base_url else None
        return frozenset(host.lower() for host in [*_split_csv(self.edu_sharing_repositories), configured] if host)

    @property
    def wikidata_db_path(self) -> Path:
        """The local Wikidata index (D43), written by ``compendium wikidata sync`` (D64) or ``build``."""
        return Path(self.state_dir) / "wikidata.db"

    @property
    def gnd_db_path(self) -> Path:
        """The local GND index (D65), written by ``compendium gnd sync`` or ``build``."""
        return Path(self.state_dir) / "gnd.db"

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

    @property
    def llm_reasoning_effort_by_prompt(self) -> dict[str, str]:
        """LLM_REASONING_EFFORTS as prompt id -> effort; an entry that is not prompt=effort is left out, the start
        names it."""
        return parse_reasoning_efforts(self.llm_reasoning_efforts)[0]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
