"""Request and response models of the legacy API (PLAN.md 8.1).

Field names, defaults and bounds are those of the old service (``alterCode/compendious``), so a caller does not
have to change anything. New options live under ``config.compendium`` and are optional. What the old service
did with an option that the new one does not have (``enable_citations``, ``educational_mode``, the linker
settings) is said in ``statistics.notes`` instead of being ignored silently.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.requests import NODE_ID_PATTERN, Extraction, Generation, Part


class InputType(StrEnum):
    TEXT = "text"
    LINKER_OUTPUT = "linker_output"


class CompendiumConfig(BaseModel):
    """``config`` of ``POST /api/v1/compendium``; the old service left ``length`` and ``language`` unbounded."""

    length: int = 6000
    enable_citations: bool = True
    educational_mode: bool = True
    language: str = "de"
    template_id: str | None = Field(None, description="New: template of the compendium; default from settings")
    collection_id: str | None = Field(None, pattern=NODE_ID_PATTERN, description="New: edu-sharing collection")
    knowledge_collection_id: str | None = Field(None, pattern=NODE_ID_PATTERN, description="New: reusable materials")
    subject: str | None = Field(None, max_length=100, description="New: subject for part 2")
    parts: list[Part] | None = Field(None, description="New: which parts to generate; default all available")
    extraction: Extraction | None = Field(None, description="New: who picks the passages (D33)")
    generation: Generation | None = Field(None, description="New: who writes the blocks (D33)")


class StrictCompendiumConfig(CompendiumConfig):
    """``config.compendium`` of the pipeline endpoints: there the old service bounded length and language."""

    length: int = Field(6000, ge=1000, le=20000)
    language: Literal["de", "en"] = "de"


class LinkerConfig(BaseModel):
    """``config.linker``; the new service resolves topics from the archives, so these are hints at most (D14)."""

    MODE: Literal["extract", "generate"] = "generate"
    MAX_ENTITIES: int = Field(10, ge=1, le=100)
    ALLOWED_ENTITY_TYPES: str | list[str] = "auto"
    EDUCATIONAL_MODE: bool = False
    LANGUAGE: Literal["de", "en"] = "de"


class CompendiumRequest(BaseModel):
    input_type: InputType
    text: str | None = None
    linker_data: dict[str, Any] | None = None
    config: CompendiumConfig = Field(default_factory=CompendiumConfig)


class PipelineCompendiumOnlyConfig(BaseModel):
    linker: LinkerConfig = Field(default_factory=LinkerConfig)
    compendium: StrictCompendiumConfig = Field(default_factory=StrictCompendiumConfig)


class PipelineCompendiumOnlyRequest(BaseModel):
    text: str = Field(min_length=1)
    config: PipelineCompendiumOnlyConfig = Field(default_factory=PipelineCompendiumOnlyConfig)


class CompendiumResponse(BaseModel):
    markdown: str
    bibliography: str
    statistics: dict[str, Any]


class WikipediaSource(BaseModel):
    """The source of an entity as the old linker reported it; here it is the resolved archive article."""

    status: str
    label_de: str
    label_en: str | None = None
    url_de: str | None = None
    url_en: str | None = None
    extract: str | None = None
    categories: list[str] = Field(default_factory=list)
    wikidata_id: str = ""
    thumbnail_url: str | None = None
    geo_lat: float | None = None
    geo_lon: float | None = None


class EntityDetails(BaseModel):
    typ: str
    citation: str


class EntitySources(BaseModel):
    wikipedia: WikipediaSource


class Entity(BaseModel):
    entity: str
    details: EntityDetails
    sources: EntitySources


class LinkerOutput(BaseModel):
    original_text: str
    entities: list[Entity] = Field(default_factory=list)


class PipelineStatistics(BaseModel):
    processing_times: dict[str, float]
    completed_steps: int
    total_steps: int
    errors: list[str] = Field(default_factory=list)
    total_processing_time: float


class PipelineCompendiumOnlyResponse(BaseModel):
    original_text: str
    linker_output: LinkerOutput
    compendium_output: CompendiumResponse
    pipeline_statistics: PipelineStatistics


class LinkerEndpointConfig(LinkerConfig):
    """``config`` of ``POST /api/v1/linker``: there the old service defaulted to ``extract`` once a config was sent."""

    MODE: Literal["extract", "generate"] = "extract"


class LinkerRequest(BaseModel):
    text: str
    config: LinkerEndpointConfig | None = Field(
        None, description="Without a config the old service generated neighbours; with one it only extracted"
    )


class LinkerWikipediaSource(WikipediaSource):
    """The full source shape of the old linker answer; the fields the archives cannot fill stay empty."""

    internal_links: list[str] = Field(default_factory=list)
    infobox_type: str | None = None
    dbpedia_uri: str | None = None
    source: str = "zim"
    needs_fallback: bool = False
    fallback_attempts: int = 0


class LinkerEntitySources(BaseModel):
    wikipedia: LinkerWikipediaSource


class LinkerEntity(BaseModel):
    entity: str
    details: EntityDetails
    sources: LinkerEntitySources
    id: str = Field(description="Stable id of the article, not a random one per request")


class LinkerStatistics(BaseModel):
    total_entities: int
    total_relationships: int = 0
    top10: dict[str, dict[str, int]] = Field(default_factory=dict)
    types_distribution: dict[str, int] = Field(default_factory=dict)
    linked: dict[str, dict[str, float]] = Field(default_factory=dict)
    relationships: dict[str, Any] = Field(default_factory=dict)
    qa_pairs: dict[str, Any] = Field(default_factory=dict)


class LinkerResponse(BaseModel):
    original_text: str
    entities: list[LinkerEntity] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    qa_pairs: list[dict[str, Any]] = Field(default_factory=list)
    statistics: LinkerStatistics


class SplitRequest(BaseModel):
    text: str = Field(min_length=1)
    chunk_size: int = Field(1000, ge=10, le=5000)
    overlap: int = Field(50, ge=0, le=500)
    split_by: Literal["sentence", "char"] = "sentence"


class SplitResponse(BaseModel):
    chunks: list[str]


class SynonymRequest(BaseModel):
    word: str = Field(min_length=1)
    max_synonyms: int = Field(5, ge=1, le=20)
    lang: str = Field("de", min_length=2, max_length=5)


class SynonymResponse(BaseModel):
    synonyms: list[str]
