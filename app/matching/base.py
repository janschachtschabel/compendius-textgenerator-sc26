"""Common matcher interface and helpers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from app.domain.models import Chunk, ScoredChunk
from app.templates.schema import TemplateSlot

_TOKEN_RE = re.compile(r"[a-zäöüß0-9]+")
_STOPWORDS = frozenset(
    """
    der die das des dem den ein eine einer eines einem einen und oder aber auch als bei mit ohne von vom zu zum zur
    für fuer im in ins an am auf aus nach über unter vor durch gegen um bis seit wird werden wurde wurden ist sind war
    waren sein hat haben hatte hatten kann können konnte nicht nur noch sich so wie was wer wo dass ob es er sie wir ihr
    man diese dieser dieses diesen jene alle allen alles andere anderen mehr sehr etwa z b zb bzw sowie dabei dazu
    daher dann dort hier heute schon bereits sowohl weder noch zwischen während wegen trotz statt keine keinen reine
    reinen baustein bausteine siehe
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens without stopwords (German)."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2 and t not in _STOPWORDS]


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
