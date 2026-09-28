"""Template schema, validated on load and on save.

A template describes part 1: which building blocks a compendium has, what belongs in each of them and
how much room each one gets. It is caller-facing — ``PUT /api/v2/templates/{id}`` takes one — so every
field here carries its own explanation; ``/docs`` shows nothing else about them.
"""

from __future__ import annotations

import importlib
import re
from typing import Annotated, Any, Literal

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
# A block's id and key stand in the markers of a compendium and its title is a heading line: an id with a space or
# "-->", or a title over two lines, left parse_document reading two of four blocks, and existing_markdown replaced
# even reviewed ones without a word (audit 2026-09-28, AP-04)
SLOT_ID_PATTERN = rf"^[\w-]{{1,{SLOT_ID_MAX_CHARS}}}$"
ONE_LINE = r"^[^\r\n]+$"
# Bounds of what a template holds, well above the built-in ones (sc26: 365 characters of description, 11 search
# words, 967 characters of assignment rules)
TITLE_MAX_CHARS = 200
TEXT_MAX_CHARS = 2_000
RULES_MAX_CHARS = 8_000
ITEMS_MAX = 30
ITEM_MAX_CHARS = 300
PATTERNS_MAX = 20
Item = Annotated[str, Field(max_length=ITEM_MAX_CHARS)]
# The standard library's own parser of patterns, private but in every CPython since 3.11 (tests/test_template_bounds.py
# holds what it is used for); mypy has no stubs for it
_PARSER: Any = importlib.import_module("re._parser")
_CODES: Any = importlib.import_module("re._constants")

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

    required: list[Item] = Field(
        default_factory=list,
        max_length=ITEMS_MAX,
        description="Facet names the block has to carry; the lint reports a missing one",
    )
    allowed: list[Item] = Field(
        default_factory=list,
        max_length=ITEMS_MAX,
        description="Further facet names the block may carry, on top of the catalogue's",
    )
    defaults: dict[Item, Item] = Field(
        default_factory=dict,
        max_length=ITEMS_MAX,
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


def nested_quantifier(pattern: str) -> bool:
    """Whether a repeat of ``pattern`` that has no upper bound holds another repeat of more than one pass, as (a+)+ or
    (a*)* or a repeated group of words do. Such a pattern tries every way to split a heading that nearly matches: its
    time grows exponentially with the length of the heading."""
    repeats = {_CODES.MAX_REPEAT, _CODES.MIN_REPEAT, _CODES.POSSESSIVE_REPEAT}

    def within(items: Any, unbounded_around: bool) -> bool:
        for code, value in items:
            if code in repeats:
                _low, high, inner = value
                if unbounded_around and high > 1:
                    return True
                parts = [(inner, unbounded_around or high == _CODES.MAXREPEAT)]
            elif code == _CODES.SUBPATTERN:
                parts = [(value[-1], unbounded_around)]
            elif code == _CODES.BRANCH:
                parts = [(branch, unbounded_around) for branch in value[1]]
            elif code in (_CODES.ASSERT, _CODES.ASSERT_NOT):
                parts = [(value[1], unbounded_around)]
            elif code == _CODES.ATOMIC_GROUP:
                parts = [(value, unbounded_around)]
            elif code == _CODES.GROUPREF_EXISTS:
                parts = [(branch, unbounded_around) for branch in value[1:] if branch is not None]
            else:
                continue
            if any(within(part, around) for part, around in parts):
                return True
        return False

    return within(_PARSER.parse(pattern), False)


def block_key(key: str) -> str:
    """A block key as the answer and the template are compared: a custom template's "Praxis" was unknown to
    every answer, which the model gives in lower case (audit 2026-09-27, KO-07)."""
    return key.strip().lower()


class TemplateSlot(OneSpelling):
    """One building block of part 1; its text in one spelling, as the archives write theirs (app/domain/spelling.py)."""

    id: str = Field(
        pattern=SLOT_ID_PATTERN,
        description="Unique within the template; identifies the block in the answer and in audits. Letters, digits, "
        "underscore and hyphen, as it stands in the markers of the text",
    )
    slot: str = Field(
        pattern=SLOT_ID_PATTERN,
        description="Stable slot key, e.g. 'entwicklung_ausblick'; letters, digits, underscore and hyphen",
    )
    title: str = Field(
        max_length=TITLE_MAX_CHARS,
        pattern=ONE_LINE,
        description="Heading of the block in the finished text, on one line, and part of its matching query",
    )
    description: str = Field(
        "", max_length=TEXT_MAX_CHARS, description="What the block is for; read by the matching and by the LLM prompts"
    )
    inclusions: str = Field(
        "", max_length=TEXT_MAX_CHARS, description="What belongs in the block, in prose; part of its matching query"
    )
    exclusions: str = Field(
        "",
        max_length=TEXT_MAX_CHARS,
        description="What does not belong in the block, in prose. Words of five letters or more become signals "
        "against a passage; a number in brackets is a reference to another block and is ignored",
    )
    sub_items: list[Item] = Field(
        default_factory=list,
        max_length=ITEMS_MAX,
        description="Aspects the block should cover; part of its matching query and its prompt",
    )
    search_queries: list[Item] = Field(
        default_factory=list,
        max_length=ITEMS_MAX,
        description="Extra words for the block's matching query; the first three also search the archives for "
        "further articles on the topic",
    )
    heading_patterns: list[Item] = Field(
        default_factory=list,
        max_length=PATTERNS_MAX,
        description="Regex patterns added to the lexicon; none with a repeat inside an unbounded repeat, as (a+)+",
    )
    facets: FacetSpec = Field(default_factory=FacetSpec, description="Facets of this block, beyond the catalogue's")
    budget: SlotBudget = Field(default_factory=SlotBudget, description="How much material this block gets")
    generator: Generator = Field(
        "",
        description="Empty (the default): the block is filled from the sources. sources, glossary or actors: the "
        "service makes the list of sources, the glossary or the list of actors instead",
    )
    source_preference: list[Item] = Field(
        default_factory=list,
        max_length=ITEMS_MAX,
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
            if nested_quantifier(pattern):
                raise ValueError(
                    f"verschachtelte Quantoren in {pattern!r}: eine Wiederholung in einer unbegrenzten Wiederholung "
                    "braucht bei einer fast passenden Überschrift exponentiell viel Zeit"
                )
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
    name: str = Field(max_length=TITLE_MAX_CHARS, description="Readable name, shown in the template list")
    description: str = Field("", max_length=TEXT_MAX_CHARS, description="What this template is for")
    empty_slot_policy: Literal["omit", "note"] = Field(
        "omit",
        description="What happens to a block for which no passage was found: omit leaves it out of the text, "
        "note keeps its heading with a line saying so. A request can override it",
    )
    default_slot: str | None = Field(
        None,
        max_length=SLOT_ID_MAX_CHARS,
        description="Slot key for topical chunks without a confident match (PLAN.md 4.4, stage 3)",
    )
    assignment_rules: str = Field(
        "",
        max_length=RULES_MAX_CHARS,
        description="Rules for matcher=llm beyond the blocks' own descriptions, in prose, naming blocks by their "
        "slot key; empty: the model assigns by the descriptions alone",
    )
    slots: list[TemplateSlot] = Field(
        max_length=MAX_SLOTS,
        description="The blocks, in reading order; at least one and at most as many as regenerate_sections may name, "
        "and their ids have to be unique",
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

    def generated_keys(self) -> frozenset[str]:
        """The lexicon keys whose paragraphs are material of a generated block rather than of a content block: each
        generated block's key, and the shared lexicon's persons when an actors block takes them, whatever the template
        calls it. The rules and matcher=llm leave these paragraphs out alike; matcher=llm offered the persons to the
        model when the actors block had another name (audit 2026-09-28, WA-07)."""
        keys = {slot.slot for slot in self.slots if slot.is_generated}
        if any(slot.generator == "actors" for slot in self.slots):
            keys.add(ACTORS_KEY)
        return frozenset(keys)
