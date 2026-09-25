"""Run the matching pipeline against gold files (PLAN.md 4.5): export for labelling, compare, evaluate.

The runner reuses ``CompendiumService.prepare`` so that evaluation sees exactly the corpus and
chunks the service would use, and ``CompendiumService.match`` once per strategy on those chunks.
With ``llm_extraction`` it also scores what ``extraction=llm`` prints on top of the default strategy
(``<strategy>+llm``, D33); that costs one LLM call per block with candidates.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.requests import GenerateRequest
from app.matching.eval import (
    Alignment,
    EvalResult,
    aggregate,
    align,
    evaluate,
    predictions_from_assignment,
    predictions_from_classification,
    predictions_from_selection,
)
from app.matching.gold import GoldSet, export_csv, load_gold
from app.service import CompendiumService, TopicNotFoundError

log = logging.getLogger(__name__)

DEFAULT_MATCHERS: tuple[str, ...] = ("lexicon_only", "bm25", "char_tfidf", "hybrid_light")
DEFAULT_TARGET_LENGTH = 12_000
LLM_SUFFIX = "+llm"


@dataclass
class MatcherOutcome:
    metrics: EvalResult | None = None  # classification before the budgets (the quality gate)
    selection: EvalResult | None = None  # what the budgets let through into the text


@dataclass
class CompareResult:
    alignment: Alignment | None
    results: dict[str, MatcherOutcome] = field(default_factory=dict)
    llm_note: str | None = None  # why the LLM extraction was not evaluated


@dataclass
class TopicRun:
    topic: str
    gold: GoldSet
    alignment: Alignment
    results: dict[str, EvalResult] = field(default_factory=dict)  # classification before the budgets
    printed: dict[str, EvalResult] = field(default_factory=dict)  # what the text prints, also <strategy>+llm
    llm_note: str | None = None


@dataclass
class EvalReport:
    runs: list[TopicRun] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # gold topics the archives could not resolve
    aggregate: dict[str, EvalResult] = field(default_factory=dict)  # classification, strategies only
    printed: dict[str, EvalResult] = field(default_factory=dict)  # printed paragraphs, also <strategy>+llm
    llm_note: str | None = None  # why the LLM extraction was not evaluated


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
    gold: GoldSet | None = None,
    template_id: str | None = None,
    target_length: int = DEFAULT_TARGET_LENGTH,
    llm_extraction: bool = False,
) -> CompareResult:
    """Prepare the topic once and run every strategy on the same chunks; with ``gold`` the metrics of each."""
    prepared = service.prepare(GenerateRequest(topic=topic, template_id=template_id))
    title = prepared.resolution.title or topic
    alignment = align(gold, prepared.chunks) if gold is not None else None
    slot_keys = [slot.slot for slot in prepared.template.content_slots()]
    result = CompareResult(alignment=alignment)
    matched_by_name = {}
    for name in matchers:
        matched = matched_by_name[name] = service.match(prepared, name, target_length)
        classified = predictions_from_classification(matched.assignment.classified, prepared.template)
        selected = predictions_from_assignment(matched.assignment.assigned, prepared.template)
        metrics: EvalResult | None = None
        selection: EvalResult | None = None
        if alignment is not None:
            metrics = evaluate(title, alignment.gold_by_chunk, classified, slot_keys, matcher=name)
            metrics.stale_labels = len(alignment.stale)
            metrics.duration_ms = matched.duration_ms
            selection = evaluate(title, alignment.gold_by_chunk, selected, slot_keys, matcher=name)
        result.results[name] = MatcherOutcome(metrics=metrics, selection=selection)
    if llm_extraction and matchers:
        base = service.settings.matcher_default if service.settings.matcher_default in matchers else matchers[0]
        result.llm_note = service.llm_unavailable()
        if result.llm_note is None:
            name = f"{base}{LLM_SUFFIX}"
            started = time.perf_counter()
            extracted = service.extract(prepared, matched_by_name[base], target_length)
            duration_ms = int((time.perf_counter() - started) * 1000)
            if extracted is not None:
                selected = predictions_from_selection(extracted.assigned, prepared.template)
                metrics = None
                if alignment is not None:
                    metrics = evaluate(title, alignment.gold_by_chunk, selected, slot_keys, matcher=name)
                    metrics.stale_labels = len(alignment.stale)
                    metrics.duration_ms = duration_ms
                    metrics.llm_tokens = extracted.report.total_tokens
                    metrics.llm_fallbacks = len(extracted.report.fallbacks)
                # The choice is what the text prints: classification and selection are the same here
                result.results[name] = MatcherOutcome(metrics=metrics, selection=metrics)
    return result


def evaluate_topic(
    service: CompendiumService,
    gold: GoldSet,
    matchers: Sequence[str] = DEFAULT_MATCHERS,
    template_id: str | None = None,
    target_length: int = DEFAULT_TARGET_LENGTH,
    llm_extraction: bool = False,
) -> TopicRun:
    """Evaluate every strategy against one gold set (and the LLM extraction when asked)."""
    compared = compare_topic(
        service,
        gold.topic,
        matchers,
        gold=gold,
        template_id=template_id or gold.template_id,
        target_length=target_length,
        llm_extraction=llm_extraction,
    )
    assert compared.alignment is not None  # noqa: S101 - there is gold here, so there is an alignment
    # The LLM's choice has no classification before budgets; it is compared with what the rules print
    results = {
        name: outcome.metrics
        for name, outcome in compared.results.items()
        if outcome.metrics is not None and not name.endswith(LLM_SUFFIX)
    }
    printed = {name: outcome.selection for name, outcome in compared.results.items() if outcome.selection is not None}
    return TopicRun(
        topic=gold.topic,
        gold=gold,
        alignment=compared.alignment,
        results=results,
        printed=printed,
        llm_note=compared.llm_note,
    )


def evaluate_gold_dir(
    service: CompendiumService,
    gold_dir: Path,
    matchers: Sequence[str] = DEFAULT_MATCHERS,
    template_id: str | None = None,
    llm_extraction: bool = False,
) -> EvalReport:
    """Evaluate every ``*.jsonl`` gold file in a directory and pool the results per strategy."""
    report = EvalReport()
    for path in sorted(Path(gold_dir).glob("*.jsonl")):
        gold = load_gold(path)
        try:
            run = evaluate_topic(service, gold, matchers, template_id, llm_extraction=llm_extraction)
        except TopicNotFoundError:
            log.warning("gold topic %s not found in the archives; skipped", gold.topic)
            report.skipped.append(gold.topic)
            continue
        report.runs.append(run)
    report.llm_note = next((run.llm_note for run in report.runs if run.llm_note), None)
    for name in dict.fromkeys(name for run in report.runs for name in run.results):
        report.aggregate[name] = aggregate([run.results[name] for run in report.runs if name in run.results])
    for name in dict.fromkeys(name for run in report.runs for name in run.printed):
        report.printed[name] = aggregate([run.printed[name] for run in report.runs if name in run.printed])
    return report
