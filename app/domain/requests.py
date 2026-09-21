"""Request model shared by API and CLI."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Part = Literal["world", "curricula", "collection"]
Extraction = Literal["rule-based", "llm"]  # who picks the sentences of part 1 (PLAN.md 4.7, D33)
Generation = Literal["rule-based", "llm-fast", "llm"]  # who writes the blocks of part 1 (PLAN.md 4.7, D33)
# Whether the writing LLM may go beyond the sources (docs/umbau.md U4); without an LLM writing, it cannot
Enrichment = Literal["sources-only", "model-knowledge"]
NODE_ID_PATTERN = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _default_parts() -> list[Part]:
    return ["world", "curricula", "collection"]


class GenerateRequest(BaseModel):
    """Either ``topic`` or ``collection_id`` is required; with both, the topic wins (PLAN.md 4.2, D12)."""

    # What /docs offers as a starting point: the shortest request that produces a whole compendium
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"topic": "Optik", "parts": ["world", "curricula"], "target_length": 8000}]}
    )

    topic: str | None = Field(None, min_length=1, max_length=300, description="Topic; default: the collection title")
    collection_id: str | None = Field(
        None, pattern=NODE_ID_PATTERN, description="edu-sharing collection: topic, subject and context; part 3"
    )
    knowledge_collection_id: str | None = Field(
        None, pattern=NODE_ID_PATTERN, description="Collection whose reusable materials feed part 1 as sources"
    )
    parts: list[Part] = Field(
        default_factory=_default_parts,
        min_length=1,
        description="Parts to generate: world (part 1), curricula (part 2), collection (part 3, needs collection_id)",
    )
    subject: str | None = Field(
        None, max_length=100, description="Subject for part 2: WLO discipline id, vocabulary URI, label or alias"
    )
    language: str = Field("de", pattern="^de$", description="Only German today; any other value is a 422")
    template_id: str | None = Field(None, description="Template id; default from settings")
    matcher: str | None = Field(None, description="Matching strategy; default from settings")
    extraction: Extraction | None = Field(
        None,
        description="Who picks the passages of part 1: rule-based (the policy's paragraphs, their first sentences) "
        "or llm (the LLM chooses sentences by number among the best candidates; the wording stays the source's); "
        "default LLM_EXTRACTION_DEFAULT. Falls back to rule-based when the b-api is not configured or not available",
    )
    generation: Generation | None = Field(
        None,
        description="Who writes the blocks of part 1: rule-based (verbatim excerpts), llm-fast (the LLM writes the "
        "blocks of LLM_FAST_SECTIONS) or llm (every content block); default LLM_GENERATION_DEFAULT. Falls back to "
        "rule-based when the b-api is not configured or not available",
    )
    enrichment: Enrichment | None = Field(
        None,
        description="Whether the LLM may add knowledge of its own beyond the sources: sources-only (default) "
        "or model-knowledge. Such sentences carry no citation number, are marked in the text as "
        "Evidenzgrad=Modellwissen and counted per block. Needs generation llm or llm-fast; with rule-based "
        "generation, or without a usable b-api, the answer reports sources-only",
    )
    target_length: int = Field(
        12_000,
        ge=2_000,
        le=60_000,
        description="Steers the length of part 1: the value is shared over the content blocks by "
        "weight, and a block stops at a paragraph boundary once it holds one and a half times its "
        "share. It is a steer, not a cap - a block is never shorter than its first paragraph, so a "
        "small value does not make a small compendium. Measured for one topic on 2026-09-21: 2 000 "
        "gave 25 784 characters, 12 000 gave 32 523, and from 20 000 on nothing grew because the "
        "sources were exhausted - more sources raise that ceiling",
    )
    empty_slot_policy: Literal["omit", "note"] | None = Field(None, description="Override the template policy")
    existing_markdown: str | None = Field(
        None,
        max_length=2_000_000,
        description="An earlier compendium: blocks marked redaktionell-geprüft are kept word for word",
    )
    regenerate_sections: list[str] | None = Field(
        None,
        description="With an earlier compendium: only these blocks are made anew, every other one is kept",
    )
    facets_visible: bool | None = Field(None, description="Override FACETS_VISIBLE")
    max_articles: int | None = Field(
        None,
        ge=1,
        le=50,
        description="Articles the corpus may hold; default CORPUS_MAX_ARTICLES. Topic and twin are always in",
    )

    @model_validator(mode="before")
    @classmethod
    def _no_mode(cls, data: Any) -> Any:
        # Unknown fields are ignored; a request that still asks for a mode must not silently run rule-based
        if isinstance(data, dict) and "mode" in data:
            raise ValueError("mode gibt es nicht mehr: extraction und generation ersetzen es (PLAN.md D33)")
        return data

    @model_validator(mode="after")
    def _topic_or_collection(self) -> GenerateRequest:
        if not self.topic and not self.collection_id:
            raise ValueError("topic oder collection_id ist erforderlich")
        # Without a collection part 3 drops out (as with the default parts); it must not be the only part
        if not self.collection_id and not {"world", "curricula"} & set(self.parts):
            raise ValueError("parts enthält nur collection; Teil 3 braucht collection_id")
        return self
