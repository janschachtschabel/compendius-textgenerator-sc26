"""Run the matching pipeline against gold files (PLAN.md 4.5): export for labelling, compare, evaluate.

The runner reuses ``CompendiumService.prepare`` so that evaluation sees exactly the corpus and
chunks the service would use, and ``CompendiumService.match`` once per strategy on those chunks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.models import Resolution
from app.domain.requests import GenerateRequest
from app.matching.eval import (
    Alignment,
    EvalResult,
    aggregate,
    align,
    evaluate,
    pairwise_agreement,
    predictions_from_assignment,
    predictions_from_classification,
)
from app.matching.gold import GoldSet, export_csv, load_gold
from app.service import CompendiumService, TopicNotFoundError

log = logging.getLogger(__name__)

DEFAULT_MATCHERS: tuple[str, ...] = ("lexicon_only", "bm25", "char_tfidf", "hybrid_light")
DEFAULT_TARGET_LENGTH = 12_000
GoldLookup = Callable[..., GoldSet | None]


@dataclass
class MatcherOutcome:
    assigned: int
    filled_slots: int
    duration_ms: int
    metrics: EvalResult | None = None  # classification before the budgets (the quality gate)
    selection: EvalResult | None = None  # what the budgets let through into the text


@dataclass
class CompareResult:
    topic: str
    resolution: Resolution
    chunks: int
    gold: GoldSet | None
    alignment: Alignment | None
    results: dict[str, MatcherOutcome] = field(default_factory=dict)
    agreement: dict[str, float] = field(default_factory=dict)


@dataclass
class TopicRun:
    topic: str
    gold: GoldSet
    alignment: Alignment
    results: dict[str, EvalResult] = field(default_factory=dict)


@dataclass
class EvalReport:
    runs: list[TopicRun] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # gold topics the archives could not resolve
    aggregate: dict[str, EvalResult] = field(default_factory=dict)


def find_gold(gold_dir: Path, *names: str) -> GoldSet | None:
    """The gold set whose topic equals one of ``names`` (case-insensitive), or ``None``."""
    wanted = {name.lower() for name in names if name}
    directory = Path(gold_dir)
    if not directory.exists():
        return None
    for path in sorted(directory.glob("*.jsonl")):
        try:
            gold = load_gold(path)
        except ValueError as exc:
            log.warning("unreadable gold file %s: %s", path, exc)
            continue
        if gold.topic.lower() in wanted:
            return gold
    return None


def export_topic(
    service: CompendiumService,
    topic: str,
    out: Path,
    template_id: str | None = None,
    matcher: str | None = None,
    target_length: int = DEFAULT_TARGET_LENGTH,
) -> tuple[Path, int]:
    """Write all chunks of a topic as review CSV; the suggestion is the policy decision before budgets."""
    prepared = service.prepare(GenerateRequest(topic=topic, template_id=template_id))
    matched = service.match(prepared, matcher, target_length)
    suggestions = predictions_from_classification(matched.assignment.classified, prepared.template)
    return export_csv(out, prepared.chunks, suggestions), len(prepared.chunks)


def compare_topic(
    service: CompendiumService,
    topic: str,
    matchers: Sequence[str] = DEFAULT_MATCHERS,
    gold_for: GoldLookup | None = None,
    template_id: str | None = None,
    target_length: int = DEFAULT_TARGET_LENGTH,
) -> CompareResult:
    """Prepare the topic once, run every strategy on the same chunks; metrics when gold exists."""
    prepared = service.prepare(GenerateRequest(topic=topic, template_id=template_id))
    title = prepared.resolution.title or topic
    gold = gold_for(topic, title) if gold_for is not None else None
    alignment = align(gold, prepared.chunks) if gold is not None else None
    slot_keys = [slot.slot for slot in prepared.template.content_slots()]
    result = CompareResult(
        topic=title, resolution=prepared.resolution, chunks=len(prepared.chunks), gold=gold, alignment=alignment
    )
    predictions: dict[str, dict[str, str]] = {}
    for name in matchers:
        matched = service.match(prepared, name, target_length)
        classified = predictions_from_classification(matched.assignment.classified, prepared.template)
        selected = predictions_from_assignment(matched.assignment.assigned, prepared.template)
        predictions[name] = classified
        metrics: EvalResult | None = None
        selection: EvalResult | None = None
        if alignment is not None:
            metrics = evaluate(title, alignment.gold_by_chunk, classified, slot_keys, matcher=name)
            metrics.stale_labels = len(alignment.stale)
            metrics.duration_ms = matched.duration_ms
            selection = evaluate(title, alignment.gold_by_chunk, selected, slot_keys, matcher=name)
        filled = sum(1 for items in matched.assignment.assigned.values() if items)
        result.results[name] = MatcherOutcome(
            assigned=len(selected),
            filled_slots=filled,
            duration_ms=matched.duration_ms,
            metrics=metrics,
            selection=selection,
        )
    result.agreement = pairwise_agreement(predictions)
    return result


def evaluate_topic(
    service: CompendiumService,
    gold: GoldSet,
    matchers: Sequence[str] = DEFAULT_MATCHERS,
    template_id: str | None = None,
    target_length: int = DEFAULT_TARGET_LENGTH,
) -> TopicRun:
    """Evaluate every strategy against one gold set."""
    compared = compare_topic(
        service,
        gold.topic,
        matchers,
        gold_for=lambda *_: gold,
        template_id=template_id or gold.template_id,
        target_length=target_length,
    )
    assert compared.alignment is not None  # noqa: S101 - gold_for always returns the gold set here
    results = {name: outcome.metrics for name, outcome in compared.results.items() if outcome.metrics is not None}
    return TopicRun(topic=gold.topic, gold=gold, alignment=compared.alignment, results=results)


def evaluate_gold_dir(
    service: CompendiumService,
    gold_dir: Path,
    matchers: Sequence[str] = DEFAULT_MATCHERS,
    template_id: str | None = None,
) -> EvalReport:
    """Evaluate every ``*.jsonl`` gold file in a directory and pool the results per strategy."""
    report = EvalReport()
    for path in sorted(Path(gold_dir).glob("*.jsonl")):
        gold = load_gold(path)
        try:
            run = evaluate_topic(service, gold, matchers, template_id)
        except TopicNotFoundError:
            log.warning("gold topic %s not found in the archives; skipped", gold.topic)
            report.skipped.append(gold.topic)
            continue
        report.runs.append(run)
    for name in matchers:
        results = [run.results[name] for run in report.runs if name in run.results]
        if results:
            report.aggregate[name] = aggregate(results)
    return report
