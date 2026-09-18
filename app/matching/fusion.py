"""Score fusion of several rankers.

Rank-only fusion (RRF) loses the magnitude of a match: a chunk that ranks first for a slot on
one weak term ties with a chunk that ranks first on four strong terms. Rankers therefore hand
over globally normalised scores (best pair of the whole run = 1.0) and the fusion takes a
weighted average, adding a small consensus bonus when several rankers agree. Weights let the
precise lexical ranker count more than the recall-oriented character n-gram ranker.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from app.domain.models import Chunk, ScoredChunk

CONSENSUS_BONUS = 0.1
SECTION_DEPTH = 2  # paragraphs share a section when the source and the first two heading levels agree


def fuse_rankings(
    rankings: Sequence[Mapping[str, Sequence[ScoredChunk]]], weights: Sequence[float] | None = None
) -> dict[str, list[ScoredChunk]]:
    """Weighted average of normalised scores per (slot, chunk); renormalised to max 1.0."""
    if not rankings:
        return {}
    weights = list(weights) if weights else [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("one weight per ranking expected")
    total_weight = sum(weights) or 1.0

    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    reasons: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    chunks: dict[str, Chunk] = {}
    for ranking, weight in zip(rankings, weights, strict=True):
        for slot_id, scored in ranking.items():
            sums.setdefault(slot_id, defaultdict(float))
            for item in scored:
                cid = item.chunk.chunk_id
                sums[slot_id][cid] += weight * item.score
                votes[slot_id][cid] += 1
                reasons[slot_id][cid].append(f"{item.matcher} {item.score:.2f}")
                chunks[cid] = item.chunk

    fused: dict[str, dict[str, float]] = {
        slot_id: {
            cid: (total / total_weight) * (1 + CONSENSUS_BONUS * (votes[slot_id][cid] - 1))
            for cid, total in per_slot.items()
        }
        for slot_id, per_slot in sums.items()
    }
    maximum = max((v for per_slot in fused.values() for v in per_slot.values()), default=0.0)
    result: dict[str, list[ScoredChunk]] = {}
    for slot_id, per_slot in fused.items():
        items = [
            ScoredChunk(
                chunk=chunks[cid],
                score=round(value / maximum, 4) if maximum > 0 else 0.0,
                matcher="fused",
                reasons=reasons[slot_id][cid],
            )
            for cid, value in per_slot.items()
        ]
        items.sort(key=lambda item: item.score, reverse=True)
        result[slot_id] = items
    return result


def smooth_sections(
    fused: dict[str, list[ScoredChunk]], chunks: Sequence[Chunk], weight: float
) -> dict[str, list[ScoredChunk]]:
    """Blend every score with the mean score of its section for the same slot (``POLICY_SECTION_SMOOTHING``).

    Paragraphs under one heading mostly belong to the same block, so a paragraph whose neighbours point elsewhere is
    probably a chance hit. The mean runs over all paragraphs of the section, silent ones included, so one strong
    paragraph cannot carry a long section; paragraphs without an own signal for the slot are not pulled in. Measured on
    2026-09-18 (eval/README.md): together with the stricter confidence threshold a third fewer wrong paragraphs are
    printed while the number of right ones stays the same. ``weight`` 0 switches it off.
    """
    if weight <= 0:
        return fused
    section_of = {
        chunk.chunk_id: (chunk.source_id, tuple(chunk.heading_path[:SECTION_DEPTH]))
        for chunk in chunks
        if chunk.heading_path
    }
    sizes: dict[tuple[str, tuple[str, ...]], int] = defaultdict(int)
    for key in section_of.values():
        sizes[key] += 1
    smoothed: dict[str, list[ScoredChunk]] = {}
    for slot_id, items in fused.items():
        totals: dict[tuple[str, tuple[str, ...]], float] = defaultdict(float)
        for item in items:
            section = section_of.get(item.chunk.chunk_id)
            if section is not None:
                totals[section] += item.score
        blended: list[ScoredChunk] = []
        for item in items:
            section = section_of.get(item.chunk.chunk_id)
            if section is None:  # lead paragraphs have no heading
                blended.append(item)
                continue
            score = (1 - weight) * item.score + weight * totals[section] / sizes[section]
            blended.append(item.model_copy(update={"score": round(score, 4)}))
        blended.sort(key=lambda item: item.score, reverse=True)
        smoothed[slot_id] = blended
    return smoothed
