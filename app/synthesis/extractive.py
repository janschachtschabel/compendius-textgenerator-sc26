"""Extractive synthesis: verbatim sentences with citation markers, no generation.

The sentences are the sources' own words, so they go into the markdown through ``escape_text``: a sentence that
quotes a tag or a link shows it as typed and runs nothing (audit 2026-09-28, SE-16). A citation's snippet stays
plain text; the table of the sources block escapes it where it prints it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.domain.models import Chunk, ChunkKind, Citation, ScoredChunk, Source
from app.knowledge.segmentation import split_sentences
from app.synthesis.safe_markdown import escape_text, unescape

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


def _select_sentences(text: str, seen: set[str], limit: int | None) -> list[str]:
    selected: list[str] = []
    for clean in usable_sentences(text):
        key = _fingerprint(clean)
        if key in seen:
            continue
        seen.add(key)
        selected.append(clean)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def _render_list(text: str) -> str:
    items = [line.strip(" -•*") for line in text.splitlines() if line.strip()]
    return "\n".join(f"- {escape_text(item)}" for item in items[:LIST_ITEMS_MAX])


def _render_table(text: str) -> str:
    rows = [line for line in text.splitlines() if "|" in line][:TABLE_ROWS_MAX]
    if not rows:
        return escape_text(text)
    cells = [[escape_text(c.strip()) for c in row.split("|")] for row in rows]
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
    all_sentences: bool = False,
) -> tuple[str, list[Citation]]:
    """Build section text from assigned chunks; every paragraph ends with its citation number, and a table has it in
    a paragraph of its own below: after the last cell GFM took it for a cell the header lacks and dropped it, and on
    the next line it became a row (audit 2026-09-29, T8).

    The rules take the first sentences of a paragraph; ``all_sentences`` keeps every usable one, for excerpts whose
    sentences the LLM already chose.
    """
    paragraphs: list[str] = []
    citations: list[Citation] = []
    number = citation_start
    for item in scored:
        chunk: Chunk = item.chunk
        source = sources.get(chunk.source_id)
        if source is None:
            continue
        if chunk.kind is not ChunkKind.TEXT:
            body = _render_list(chunk.text) if chunk.kind is ChunkKind.LIST else _render_table(chunk.text)
            key = _fingerprint(body)  # a list or table is one unit: without this it could be printed twice
            if key in seen_sentences:
                continue
            seen_sentences.add(key)
        else:
            limit = None if all_sentences else SENTENCES_PER_CHUNK + (2 if chunk.is_lead else 0)
            sentences = _select_sentences(chunk.text, seen_sentences, limit)
            if not sentences:
                continue
            body = escape_text(" ".join(sentences))
        number += 1
        citations.append(
            Citation(
                number=number,
                source_id=source.source_id,
                chunk_id=chunk.chunk_id,
                source_title=source.title,
                source_url=source.url,
                section_heading=chunk.full_heading,
                snippet=unescape(body)[:220],
            )
        )
        paragraphs.append(f"{body}\n\n[{number}]" if chunk.kind is ChunkKind.TABLE else f"{body} [{number}]")
    return "\n\n".join(paragraphs), citations
