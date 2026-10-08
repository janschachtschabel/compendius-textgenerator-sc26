"""Common matcher interface and helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import Chunk, ScoredChunk
from app.templates.schema import TemplateSlot


def slot_representation(slot: TemplateSlot) -> str:
    """Rich textual representation of a slot used as query by all rankers."""
    parts = [slot.title, slot.description, slot.inclusions]
    if slot.sub_items:
        parts.append(" ".join(slot.sub_items))
    if slot.search_queries:
        parts.append(" ".join(slot.search_queries))
    return ". ".join(p for p in parts if p).strip()


def chunk_representation(chunk: Chunk) -> str:
    return f"{chunk.full_heading}. {chunk.text}"


class Matcher(Protocol):
    """Rank chunks per slot. Returns candidates with scores in [0, 1]; no assignment decisions."""

    name: str
    weight: float

    def score(self, slots: Sequence[TemplateSlot], chunks: Sequence[Chunk]) -> dict[str, list[ScoredChunk]]: ...
