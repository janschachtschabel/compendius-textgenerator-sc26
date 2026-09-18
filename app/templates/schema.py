"""Template schema, validated on load and on save."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Generator = Literal["", "sources", "glossary", "actors"]


class FacetSpec(BaseModel):
    required: list[str] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)
    defaults: dict[str, str] = Field(default_factory=dict)


class SlotBudget(BaseModel):
    min_chunks: int = Field(1, ge=0)
    max_chunks: int = Field(4, ge=0)
    target_chars: int = Field(1500, ge=100)
    weight: float = Field(1.0, gt=0)


class TemplateSlot(BaseModel):
    """One building block of part 1."""

    id: str
    slot: str = Field(description="Stable slot key, e.g. 'entwicklung_ausblick'")
    title: str
    description: str = ""
    inclusions: str = ""
    exclusions: str = ""
    sub_items: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    heading_patterns: list[str] = Field(default_factory=list, description="Regex patterns added to the lexicon")
    facets: FacetSpec = Field(default_factory=FacetSpec)
    budget: SlotBudget = Field(default_factory=SlotBudget)
    generator: Generator = Field("", description="Non-empty for generated slots (sources, glossary, actors)")
    source_preference: list[str] = Field(default_factory=list, description="Preferred source projects")

    @property
    def is_generated(self) -> bool:
        return self.generator != ""


class Template(BaseModel):
    id: str
    version: int = 1
    name: str
    description: str = ""
    empty_slot_policy: Literal["omit", "note"] = "omit"
    default_slot: str | None = Field(
        None, description="Slot key for topical chunks without a confident match (PLAN.md 4.4, stage 3)"
    )
    slots: list[TemplateSlot]
    builtin: bool = False

    @field_validator("slots")
    @classmethod
    def _unique_ids(cls, slots: list[TemplateSlot]) -> list[TemplateSlot]:
        ids = [s.id for s in slots]
        if len(ids) != len(set(ids)):
            raise ValueError("slot ids must be unique")
        if not slots:
            raise ValueError("a template needs at least one slot")
        return slots

    @model_validator(mode="after")
    def _default_slot_is_a_content_slot(self) -> Template:
        if self.default_slot is not None:
            slot = self.slot_by_key(self.default_slot)
            if slot is None or slot.is_generated:
                raise ValueError(f"default_slot {self.default_slot!r} must name a content slot of the template")
        return self

    def slot_by_key(self, key: str) -> TemplateSlot | None:
        return next((s for s in self.slots if s.slot == key), None)

    def content_slots(self) -> list[TemplateSlot]:
        return [s for s in self.slots if not s.is_generated]
