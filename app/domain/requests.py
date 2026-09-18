"""Request model shared by API and CLI."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Part = Literal["world", "curricula", "collection"]
Mode = Literal["rule-based", "hybrid-fast", "hybrid-quality"]  # generation modes (PLAN.md 4.7, D10)
NODE_ID_PATTERN = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _default_parts() -> list[Part]:
    return ["world", "curricula", "collection"]


class GenerateRequest(BaseModel):
    """Either ``topic`` or ``collection_id`` is required; with both, the topic wins (PLAN.md 4.2, D12)."""

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
    language: str = Field("de", pattern="^de$")
    template_id: str | None = Field(None, description="Template id; default from settings")
    matcher: str | None = Field(None, description="Matching strategy; default from settings")
    mode: Mode | None = Field(
        None,
        description="rule-based (no LLM), hybrid-fast (few LLM calls) or hybrid-quality; default LLM_MODE_DEFAULT. "
        "Hybrid modes fall back to rule-based when the b-api is not configured or not available",
    )
    target_length: int = Field(12_000, ge=2_000, le=60_000, description="Approximate total characters for part 1")
    empty_slot_policy: Literal["omit", "note"] | None = Field(None, description="Override the template policy")
    facets_visible: bool | None = Field(None, description="Override FACETS_VISIBLE")
    max_articles: int | None = Field(None, ge=1, le=50)

    @model_validator(mode="after")
    def _topic_or_collection(self) -> GenerateRequest:
        if not self.topic and not self.collection_id:
            raise ValueError("topic oder collection_id ist erforderlich")
        return self
