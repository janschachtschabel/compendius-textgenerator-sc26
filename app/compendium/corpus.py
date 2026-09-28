"""Which paragraphs of the corpus part 1 uses, and the sub-topics part 2 searches for."""

from __future__ import annotations

import logging

from app.domain.models import Chunk, Source
from app.knowledge.segmentation import segment_source
from app.knowledge.topic import topic_stem
from app.matching.lexicon import HeadingLexicon
from app.sources.zim.registry import NAMED_ORIGIN, NODE_ORIGIN

log = logging.getLogger(__name__)


# Which paragraphs survive CORPUS_MAX_CHUNKS: the topic's own articles, then the materials the request asked for and
# the article of its node, then the neighbours the LLM named or links and search found. Anything else (lookups) last.
ORIGIN_PRIORITY = {
    "primary": 0,
    "same_topic": 1,
    "material": 2,
    NODE_ORIGIN: 2,
    NAMED_ORIGIN: 3,  # the LLM's articles on the parts of the topic, in place of linked ones (D63)
    "linked": 3,
    "search": 4,
}


def segment_corpus(
    sources: list[Source], lexicon: HeadingLexicon, max_chunks: int
) -> tuple[list[Chunk], list[Source], int]:
    """Segment all sources and apply the chunk cap; return chunks, the sources that kept a chunk, and the cut count.

    Articles pulled in by search or by a link that does not carry the topic in its title contribute only paragraphs
    that mention the topic. The cap is filled in ``ORIGIN_PRIORITY`` order while chunks keep the corpus order; a
    source left without chunks is not listed (the primary article always is).
    """
    primary = next((s for s in sources if s.is_primary), None)
    stem = topic_stem(primary.title) if primary else ""
    segmented: list[list[Chunk]] = []
    for source in sources:
        source_chunks = segment_source(source, lexicon)
        needs_filter = source.origin in {"linked", "search"} and stem and stem not in source.title.lower()
        if needs_filter:
            source_chunks = [c for c in source_chunks if stem in f"{c.full_heading} {c.text}".lower()]
        segmented.append(source_chunks)

    allowed = [0] * len(sources)
    budget = max_chunks
    by_priority = sorted(
        range(len(sources)), key=lambda i: (ORIGIN_PRIORITY.get(sources[i].origin, len(ORIGIN_PRIORITY)), i)
    )
    for index in by_priority:
        allowed[index] = min(len(segmented[index]), budget)
        budget -= allowed[index]

    chunks: list[Chunk] = []
    kept: list[Source] = []
    for source, source_chunks, take in zip(sources, segmented, allowed, strict=True):
        if not take and not source.is_primary:
            continue
        kept.append(source)
        chunks.extend(source_chunks[:take])
    truncated = sum(len(source_chunks) for source_chunks in segmented) - len(chunks)
    if truncated:
        log.info("corpus capped at %d chunks; %d left out", max_chunks, truncated)
    return chunks, kept, truncated


def subtopics(sources: list[Source], primary: Source | None) -> list[str]:
    """Titles of neighbouring articles that carry the topic stem: the sub-topics part 2 searches for."""
    if primary is None:
        return []
    stem = topic_stem(primary.title)
    if not stem:
        return []
    return [
        source.title
        for source in sources
        if not source.is_primary
        and source.origin in {"same_topic", NODE_ORIGIN, "linked", NAMED_ORIGIN}
        and stem in source.title.lower()
    ]
