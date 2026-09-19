"""Splitting a text into chunks for the legacy utility endpoint (PLAN.md 8.1).

The old service pre-cleaned the text (non-printable characters to space, whitespace collapsed) and then packed
sentences greedily; its ``chunk_size`` was overwritten by a setting, so the request had no say. Here the request
decides, everything else stays as it was: sentences are kept whole where they fit, the overlap repeats whole
sentences (``sentence``) or characters (``char``).
"""

from __future__ import annotations

import re

from app.knowledge.segmentation import split_sentences

_UNPRINTABLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean(text: str) -> str:
    """One line without control characters: what the old service chunked."""
    return " ".join(_UNPRINTABLE.sub(" ", text).split())


def split_text(text: str, *, chunk_size: int, overlap: int, split_by: str = "sentence") -> list[str]:
    """Chunks of at most ``chunk_size`` characters with an ``overlap``; ``split_by`` is ``sentence`` or ``char``."""
    cleaned = clean(text)
    if not cleaned:
        return []
    if split_by == "char":
        return _by_char(cleaned, chunk_size, overlap)
    return _by_sentence(cleaned, chunk_size, overlap)


def _by_char(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(end - overlap, start + 1)  # an overlap of the whole chunk would never advance
    return chunks


def _by_sentence(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Pack whole sentences; a sentence longer than the chunk is split by characters, as the old service did."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for sentence in split_sentences(text):
        if len(sentence) > chunk_size:
            if current:
                chunks.append(" ".join(current))
                current, length = [], 0
            chunks.extend(_by_char(sentence, chunk_size, overlap))
            continue
        if current and length + 1 + len(sentence) > chunk_size:
            chunks.append(" ".join(current))
            # The overlap plus the next sentence must still fit, otherwise the chunk would grow past its size
            current, length = _tail(current, min(overlap, chunk_size - len(sentence) - 1))
        current.append(sentence)
        length += (1 if length else 0) + len(sentence)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _tail(sentences: list[str], overlap: int) -> tuple[list[str], int]:
    """The last whole sentences of a chunk that fit into ``overlap``: the beginning of the next chunk."""
    tail: list[str] = []
    length = 0
    for sentence in reversed(sentences):
        if length + (1 if length else 0) + len(sentence) > overlap:
            break
        tail.insert(0, sentence)
        length += (1 if length else 0) + len(sentence)
    return tail, length
