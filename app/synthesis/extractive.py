"""Extractive synthesis: verbatim sentences with citation markers, no generation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.domain.models import Chunk, ChunkKind, Citation, ScoredChunk, Source
from app.knowledge.segmentation import split_sentences

SENTENCES_PER_CHUNK = 3
MIN_SENTENCE_CHARS = 25
LIST_ITEMS_MAX = 8
TABLE_ROWS_MAX = 8
_DANGLING_RE = re.compile(r"\b(von|mit|ist|sind|gleich|durch|für|als|und|oder|wobei|sei|seien|gilt)\s*[.,;:]")


def _fingerprint(sentence: str) -> str:
    return " ".join(sentence.lower().split()[:7])


def usable_sentences(text: str) -> list[str]:
    """Whitespace-normalised sentences that can stand in a block: long enough and not cut off by a formula."""
    usable: list[str] = []
    for sentence in split_sentences(text):
        clean = re.sub(r"\s+", " ", sentence).strip()
        if len(clean) < MIN_SENTENCE_CHARS or clean.endswith((":", ";", ",")):
            continue
        if _DANGLING_RE.search(clean):  # a formula was removed here; the sentence is incomplete
            continue
        usable.append(clean)
    return usable


def _select_sentences(text: str, seen: set[str], limit: int) -> list[str]:
    selected: list[str] = []
    for clean in usable_sentences(text):
        key = _fingerprint(clean)
        if key in seen:
            continue
        seen.add(key)
        selected.append(clean)
        if len(selected) >= limit:
            break
    return selected


def _render_list(text: str) -> str:
    items = [line.strip(" -•*") for line in text.splitlines() if line.strip()]
    return "\n".join(f"- {item}" for item in items[:LIST_ITEMS_MAX])


def _render_table(text: str) -> str:
    rows = [line for line in text.splitlines() if "|" in line][:TABLE_ROWS_MAX]
    if not rows:
        return text
    cells = [[c.strip() for c in row.split("|")] for row in rows]
    width = max(len(r) for r in cells)
    cells = [r + [""] * (width - len(r)) for r in cells]
    header = "| " + " | ".join(cells[0]) + " |"
    separator = "|" + "|".join([" --- "] * width) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in cells[1:])
    return "\n".join(part for part in (header, separator, body) if part)


def synthesize(
    scored: Sequence[ScoredChunk],
    sources: Mapping[str, Source],
    citation_start: int,
    seen_sentences: set[str],
) -> tuple[str, list[Citation]]:
    """Build section text from assigned chunks; every paragraph ends with its citation number."""
    paragraphs: list[str] = []
    citations: list[Citation] = []
    number = citation_start
    for item in scored:
        chunk: Chunk = item.chunk
        source = sources.get(chunk.source_id)
        if source is None:
            continue
        if chunk.kind is ChunkKind.LIST:
            body = _render_list(chunk.text)
        elif chunk.kind is ChunkKind.TABLE:
            body = _render_table(chunk.text)
        else:
            limit = SENTENCES_PER_CHUNK + (2 if chunk.is_lead else 0)
            sentences = _select_sentences(chunk.text, seen_sentences, limit)
            if not sentences:
                continue
            body = " ".join(sentences)
        number += 1
        citations.append(
            Citation(
                number=number,
                source_id=source.source_id,
                chunk_id=chunk.chunk_id,
                source_title=source.title,
                source_url=source.url,
                section_heading=chunk.full_heading,
                snippet=body[:220],
            )
        )
        paragraphs.append(f"{body} [{number}]")
    return "\n\n".join(paragraphs), citations
