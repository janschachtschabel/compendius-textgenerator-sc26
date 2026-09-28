"""Template schema, validated on load and on save.

A template describes part 1: which building blocks a compendium has, what belongs in each of them and
how much room each one gets. It is caller-facing — ``PUT /api/v2/templates/{id}`` takes one — so every
field here carries its own explanation; ``/docs`` shows nothing else about them.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.spelling import OneSpelling

Generator = Literal["", "sources", "glossary", "actors"]
Role = Literal["", "definition", "systematik", "context"]
# A template id names the file it is stored in: letters, digits, underscore and hyphen, nothing that leads out of
# the directory (audit 2026-09-27, SE-09)
TEMPLATE_ID_PATTERN = r"^[\w-]{1,80}$"
# Bounds of a template's blocks, and of the names regenerate_sections may send (audit 2026-09-28, SE-15): sc26
# has 13 blocks, and a block id is as short as a template id
MAX_SLOTS = 60
SLOT_ID_MAX_CHARS = 80

# The keys of the shared heading lexicon (config/heading_lexicon.yaml) that stand for a role. A template that names
# no role takes its roles from them, as the built-in templates were read before roles (audit 2026-09-27, AR-04).
ROLE_KEYS: dict[str, Role] = {
    "themendefinition": "definition",
    "definition": "definition",
    "systematik": "systematik",
    "gesellschaftlicher_kontext": "context",
}
ACTORS_KEY = "akteure"  # where the shared lexicon files the sections on persons: material of the actors block


class FacetSpec(BaseModel):
    """Which facets a block carries, beyond the ones ``config/facets.yaml`` declares for its slot."""

    required: list[str] = Field(
        default_factory=list, description="Facet names the block has to carry; the lint reports a missing one"
    )
    allowed: list[str] = Field(
        default_factory=list, description="Further facet names the block may carry, on top of the catalogue's"
    )
    defaults: dict[str, str] = Field(
        default_factory=dict,
        description="Facet name to value, used when the block carries no value of its own and the facet is allowed",
    )


class SlotBudget(BaseModel):
    """How much material a block gets. A steer, not a cap: excerpts end at a paragraph boundary."""

    min_chunks: int = Field(1, ge=0, description="Below this many passages the block keeps collecting")
    max_chunks: int = Field(4, ge=0, description="At this many passages the block stops collecting")
    target_chars: int = Field(
        1500,
        ge=100,
        description="Characters aimed at: collecting stops at a paragraph boundary once one and a half times this "
        "is reached, and the LLM prompts name it as the target length. For a content block the request sets it: "
        "its target_length (12,000 unless it names another) is shared over the content blocks by weight, so in a "
        "template weight is what steers a block's length, not this number",
    )
    weight: float = Field(
        1.0, gt=0, description="This block's share when a request's target_length is distributed over the blocks"
    )


def block_key(key: str) -> str:
    """A block key as the answer and the template are compared: a custom template's "Praxis" was unknown to
    every answer, which the model gives in lower case (audit 2026-09-27, KO-07)."""
    return key.strip().lower()


class TemplateSlot(OneSpelling):
    """One building block of part 1; its text in one spelling, as the archives write theirs (app/domain/spelling.py)."""

    id: str = Field(description="Unique within the template; identifies the block in the answer and in audits")
    slot: str = Field(description="Stable slot key, e.g. 'entwicklung_ausblick'")
    title: str = Field(description="Heading of the block in the finished text, and part of its matching query")
    description: str = Field("", description="What the block is for; read by the matching and by the LLM prompts")
    inclusions: str = Field("", description="What belongs in the block, in prose; part of its matching query")
    exclusions: str = Field(
        "",
        description="What does not belong in the block, in prose. Words of five letters or more become signals "
        "against a passage; a number in brackets is a reference to another block and is ignored",
    )
    sub_items: list[str] = Field(
        default_factory=list, description="Aspects the block should cover; part of its matching query and its prompt"
    )
    search_queries: list[str] = Field(
        default_factory=list,
        description="Extra words for the block's matching query; the first three also search the archives for "
        "further articles on the topic",
    )
    heading_patterns: list[str] = Field(default_factory=list, description="Regex patterns added to the lexicon")
    facets: FacetSpec = Field(default_factory=FacetSpec, description="Facets of this block, beyond the catalogue's")
    budget: SlotBudget = Field(default_factory=SlotBudget, description="How much material this block gets")
    generator: Generator = Field(
        "",
        description="Empty (the default): the block is filled from the sources. sources, glossary or actors: the "
        "service makes the list of sources, the glossary or the list of actors instead",
    )
    source_preference: list[str] = Field(
        default_factory=list,
        description="Preferred source projects, best first; a passage from the first one scores highest",
    )
    role: Role = Field(
        "",
        description="What the block is to the rules beyond its text. definition: the lead of the main article and "
        "the definitions of the topic go here; systematik: the introductions of the sub-areas; context: where "
        "statements of relevance belong. Empty: none of these. A template that names no role at all takes them from "
        "the keys themendefinition, systematik and gesellschaftlicher_kontext, as sc26 names its blocks",
    )

    @property
    def is_generated(self) -> bool:
        return self.generator != ""

    @field_validator("heading_patterns")
    @classmethod
    def _patterns_compile(cls, patterns: list[str]) -> list[str]:
        # The lexicon compiles them for every compendium; a broken one used to be stored and then answer every
        # request with the template with a 500 (review 2026-09-25)
        for pattern in patterns:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"kein gültiger regulärer Ausdruck: {pattern!r} ({exc})") from exc
        return patterns

    @field_validator("slot")
    @classmethod
    def _one_spelling(cls, value: str) -> str:
        # KO-07 took "Praxis" into matcher=llm only; the roles, the lexicon, the facets and the actors compared keys
        # exactly and lost such a block's role and the lead (audit 2026-09-28, KO-22). One spelling from the start.
        return block_key(value)


class Template(OneSpelling):
    """The building blocks of part 1, in the order they appear in the finished text."""

    id: str = Field(
        pattern=TEMPLATE_ID_PATTERN,
        description="Identifies the template; the same id in the path and in the body when saving. Letters, digits, "
        "underscore and hyphen: the id names the file the template is stored in",
    )
    version: int = Field(1, description="Counted up on every save; not to be set by the caller")
    name: str = Field(description="Readable name, shown in the template list")
    description: str = Field("", description="What this template is for")
    empty_slot_policy: Literal["omit", "note"] = Field(
        "omit",
        description="What happens to a block for which no passage was found: omit leaves it out of the text, "
        "note keeps its heading with a line saying so. A request can override it",
    )
    default_slot: str | None = Field(
        None, description="Slot key for topical chunks without a confident match (PLAN.md 4.4, stage 3)"
    )
    assignment_rules: str = Field(
        "",
        description="Rules for matcher=llm beyond the blocks' own descriptions, in prose, naming blocks by their "
        "slot key; empty: the model assigns by the descriptions alone",
    )
    slots: list[TemplateSlot] = Field(
        description="The blocks, in reading order; at least one, and their ids have to be unique"
    )
    builtin: bool = Field(
        False, description="Built-in templates ship with the image and are write-protected (409); not to be set"
    )

    @field_validator("slots")
    @classmethod
    def _unique_ids(cls, slots: list[TemplateSlot]) -> list[TemplateSlot]:
        ids = [s.id for s in slots]
        if len(ids) != len(set(ids)):
            raise ValueError("slot ids must be unique")
        keys = [block_key(s.slot) for s in slots]  # "Praxis" and "praxis" would be one block to matcher=llm
        if len(keys) != len(set(keys)):
            raise ValueError("slot keys must be unique, in whatever case")
        if not slots:
            raise ValueError("a template needs at least one slot")
        return slots

    @model_validator(mode="after")
    def _roles_from_keys(self) -> Template:
        # A template written before roles keeps working as it did; one that names a role says all of them
        if not any(slot.role for slot in self.slots):
            self.slots = [
                slot.model_copy(update={"role": ROLE_KEYS[slot.slot]})
                if slot.slot in ROLE_KEYS and not slot.is_generated
                else slot
                for slot in self.slots
            ]
        return self

    @field_validator("default_slot")
    @classmethod
    def _default_in_one_spelling(cls, value: str | None) -> str | None:
        return block_key(value) if value is not None else None

    @model_validator(mode="after")
    def _default_slot_is_a_content_slot(self) -> Template:
        if self.default_slot is not None:
            slot = self.slot_by_key(self.default_slot)
            if slot is None or slot.is_generated:
                raise ValueError(f"default_slot {self.default_slot!r} must name a content slot of the template")
        return self

    def slot_by_key(self, key: str) -> TemplateSlot | None:
        return next((s for s in self.slots if block_key(s.slot) == block_key(key)), None)

    def content_slots(self) -> list[TemplateSlot]:
        return [s for s in self.slots if not s.is_generated]
