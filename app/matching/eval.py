"""Metrics against the gold standard (PLAN.md 4.5).

Per slot: precision, recall, F1 over the labelled chunks of a topic. Macro-F1 averages the slots
that have gold support; a slot predicted although the gold standard holds no chunk for it is a
"hallucination slot" and reported separately, an untouched unsupported slot is "honestly empty".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, computed_field

from app.domain.models import Chunk, ScoredChunk
from app.knowledge.segmentation import split_sentences
from app.matching.gold import GoldLabel, GoldSet, text_hash
from app.templates.schema import Template


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


class SlotMetrics(BaseModel):
    slot: str
    support: int = Field(0, description="Gold chunks of this slot")
    predicted: int = Field(0, description="Chunks assigned to this slot")
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def f1(self) -> float:
        return _f1(self.precision, self.recall)


class EvalResult(BaseModel):
    topic: str
    topics: list[str] = Field(default_factory=list)
    matcher: str = ""
    slots: list[SlotMetrics]
    labeled: int
    assigned: int
    misassigned: int = Field(description="Assigned chunks whose gold slot differs (including gold = none)")
    missed: int = Field(description="Gold chunks left unassigned")
    hallucination_slots: list[str]
    honest_empty_slots: list[str]
    confusion: dict[str, int] = Field(default_factory=dict, description="'gold>predicted' -> count, mismatches only")
    stale_labels: int = 0
    duration_ms: int = 0
    llm_tokens: int = Field(0, description="Tokens the LLM spent choosing the passages (extraction=llm)")
    llm_fallbacks: int = Field(0, description="Blocks that kept the rule-based paragraphs although the LLM was asked")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def macro_f1(self) -> float:
        supported = [m.f1 for m in self.slots if m.support > 0]
        return sum(supported) / len(supported) if supported else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def micro_f1(self) -> float:
        tp = sum(m.tp for m in self.slots)
        fp = sum(m.fp for m in self.slots)
        fn = sum(m.fn for m in self.slots)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return _f1(precision, recall)


def evaluate(
    topic: str,
    gold_by_chunk: Mapping[str, str | None],
    predicted: Mapping[str, str],
    slot_keys: Sequence[str],
    matcher: str = "",
) -> EvalResult:
    """Compare predictions with gold labels; chunks without a gold label are ignored."""
    counts = {key: SlotMetrics(slot=key) for key in slot_keys}
    confusion: dict[str, int] = {}
    assigned = misassigned = missed = 0
    for chunk_id, gold in gold_by_chunk.items():
        pred = predicted.get(chunk_id)
        if gold is not None and gold in counts:
            counts[gold].support += 1
        if pred is None:
            if gold is not None:
                missed += 1
                if gold in counts:
                    counts[gold].fn += 1
            continue
        assigned += 1
        if pred in counts:
            counts[pred].predicted += 1
        if pred == gold:
            counts[pred].tp += 1
            continue
        misassigned += 1
        key = f"{gold or 'none'}>{pred}"
        confusion[key] = confusion.get(key, 0) + 1
        if pred in counts:
            counts[pred].fp += 1
        if gold is not None and gold in counts:
            counts[gold].fn += 1
    return EvalResult(
        topic=topic,
        topics=[topic],
        matcher=matcher,
        slots=list(counts.values()),
        labeled=len(gold_by_chunk),
        assigned=assigned,
        misassigned=misassigned,
        missed=missed,
        hallucination_slots=[k for k, m in counts.items() if m.support == 0 and m.predicted > 0],
        honest_empty_slots=[k for k, m in counts.items() if m.support == 0 and m.predicted == 0],
        confusion=confusion,
    )


def aggregate(results: Sequence[EvalResult]) -> EvalResult:
    """Pool the counts of several topics; macro-F1 is then computed over the pooled slots."""
    pooled: dict[str, SlotMetrics] = {}
    confusion: dict[str, int] = {}
    for result in results:
        for key, count in result.confusion.items():
            confusion[key] = confusion.get(key, 0) + count
        for metrics in result.slots:
            total = pooled.setdefault(metrics.slot, SlotMetrics(slot=metrics.slot))
            total.support += metrics.support
            total.predicted += metrics.predicted
            total.tp += metrics.tp
            total.fp += metrics.fp
            total.fn += metrics.fn
    return EvalResult(
        topic="gesamt",
        topics=[r.topic for r in results],
        matcher=results[0].matcher if results else "",
        slots=list(pooled.values()),
        labeled=sum(r.labeled for r in results),
        assigned=sum(r.assigned for r in results),
        misassigned=sum(r.misassigned for r in results),
        missed=sum(r.missed for r in results),
        hallucination_slots=sorted({slot for r in results for slot in r.hallucination_slots}),
        honest_empty_slots=[k for k, m in pooled.items() if m.support == 0 and m.predicted == 0],
        confusion=dict(sorted(confusion.items(), key=lambda item: -item[1])),
        stale_labels=sum(r.stale_labels for r in results),
        duration_ms=sum(r.duration_ms for r in results),
        llm_tokens=sum(r.llm_tokens for r in results),
        llm_fallbacks=sum(r.llm_fallbacks for r in results),
    )


@dataclass
class Alignment:
    """Gold labels attached to the current chunks of a topic."""

    gold_by_chunk: dict[str, str | None] = field(default_factory=dict)
    stale: list[GoldLabel] = field(default_factory=list)
    matched_by_id: int = 0


def align(gold: GoldSet, chunks: Sequence[Chunk]) -> Alignment:
    """Match labels to chunks by text hash, then leftover labels by chunk id; each label is used once.

    The id pass comes second so that a dropped paragraph, which shifts the positions of all
    following chunks, cannot attach an already matched label to its neighbour.
    """
    by_hash = gold.by_hash()
    by_id = gold.by_id()
    alignment = Alignment()
    used: set[int] = set()
    unmatched: list[Chunk] = []
    for chunk in chunks:
        label = by_hash.get(text_hash(chunk.text))
        if label is None or id(label) in used:
            unmatched.append(chunk)
            continue
        alignment.gold_by_chunk[chunk.chunk_id] = label.slot
        used.add(id(label))
    for chunk in unmatched:
        label = by_id.get(chunk.chunk_id)
        if label is None or id(label) in used:
            continue
        alignment.gold_by_chunk[chunk.chunk_id] = label.slot
        alignment.matched_by_id += 1
        used.add(id(label))
    alignment.stale = [label for label in gold.labels if id(label) not in used]
    return alignment


def predictions_from_assignment(assigned: Mapping[str, Sequence[ScoredChunk]], template: Template) -> dict[str, str]:
    """Chunk id -> slot key for every assigned chunk."""
    key_of = {slot.id: slot.slot for slot in template.slots}
    return {
        scored.chunk.chunk_id: key_of[slot_id]
        for slot_id, items in assigned.items()
        if slot_id in key_of
        for scored in items
    }


def predictions_from_selection(assigned: Mapping[str, Sequence[ScoredChunk]], template: Template) -> dict[str, str]:
    """Chunk id -> slot key where the text prints most of the chunk's sentences (extraction=llm, D33).

    The LLM may take sentences of one paragraph for several blocks; the gold standard knows one block per
    paragraph. A tie goes to the block that comes first in the template.
    """
    best: dict[str, tuple[int, str]] = {}
    for slot in template.slots:
        for item in assigned.get(slot.id, []):
            count = max(1, len(split_sentences(item.chunk.text)))
            known = best.get(item.chunk.chunk_id)
            if known is None or count > known[0]:
                best[item.chunk.chunk_id] = (count, slot.slot)
    return {chunk_id: key for chunk_id, (_, key) in best.items()}


def pairwise_agreement(predictions: Mapping[str, Mapping[str, str]]) -> dict[str, float]:
    """Jaccard overlap of the (chunk, slot) pairs for every pair of strategies, keyed ``a|b``."""
    names = list(predictions)
    pairs = {name: {(chunk, slot) for chunk, slot in predicted.items()} for name, predicted in predictions.items()}
    agreement: dict[str, float] = {}
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            union = pairs[first] | pairs[second]
            agreement[f"{first}|{second}"] = len(pairs[first] & pairs[second]) / len(union) if union else 1.0
    return agreement


def predictions_from_classification(classified: Mapping[str, str], template: Template) -> dict[str, str]:
    """Chunk id -> slot key for the policy decision before the slot budgets cut the selection."""
    key_of = {slot.id: slot.slot for slot in template.slots}
    return {chunk_id: key_of[slot_id] for chunk_id, slot_id in classified.items() if slot_id in key_of}
