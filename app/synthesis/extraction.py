"""Extraction of part 1 (PLAN.md 4.7, D33): which sentences of which paragraphs go into each block.

Rule-based, the policy assigns whole paragraphs to the blocks and the writer takes their first sentences. With
``extraction=llm`` the model chooses the sentences of every content block among candidates: the paragraphs the
policy gave the block, then the next best by the policy's score for that block. The choices run in parallel, one
call per block with candidates. A block whose choice fails (b-api, budget, time, unreadable answer, unexpected
error) keeps the policy's paragraphs, and the reason goes to the audit; a block where no offered paragraph fits
stays empty.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.domain.models import Chunk, ScoredChunk, Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped
from app.llm.deadline import Deadline
from app.matching.policy import AssignmentResult
from app.synthesis.selection import LlmSelector, Selection
from app.templates.schema import Template, TemplateSlot

log = logging.getLogger(__name__)

RUNNER_UP_REASON = "Kandidat nach Policy-Score"


@dataclass
class ExtractionJob:
    """What ``extraction=llm`` needs: the selector, the request budget and how many paragraphs to offer."""

    selector: LlmSelector
    budget: RequestBudget
    topic: str
    candidates: int = 8
    concurrency: int = 4
    deadline: Deadline | None = None


@dataclass
class ExtractionReport:
    slots: list[str] = field(default_factory=list)  # blocks whose sentences the LLM chose
    emptied: list[str] = field(default_factory=list)  # of those: no offered paragraph fit, the block stays empty
    fallbacks: dict[str, str] = field(default_factory=dict)  # slot id -> why the policy's paragraphs stayed
    prompts: set[str] = field(default_factory=set)
    model: str | None = None
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    sentences: int = 0
    invalid: int = 0  # numbers in answers that were not offered
    cut: int = 0  # chosen sentences left out for length


@dataclass
class Extracted:
    assigned: dict[str, list[ScoredChunk]]  # per slot: excerpts where the LLM chose, else the policy's paragraphs
    selected: set[str]  # slots whose excerpts the LLM chose; the writer keeps all their sentences
    report: ExtractionReport


def candidates_for(
    slot_id: str, assignment: AssignmentResult, chunks: Mapping[str, Chunk], limit: int
) -> list[ScoredChunk]:
    """The policy's paragraphs of the block first (all of them), then the next best by its score, up to ``limit``."""
    offered = list(assignment.assigned.get(slot_id, []))
    seen = {item.chunk.chunk_id for item in offered}
    ranked = sorted(assignment.slot_scores.get(slot_id, {}).items(), key=lambda item: -item[1])
    for chunk_id, score in ranked:
        if len(offered) >= limit:
            break
        if chunk_id in seen or chunk_id not in chunks:
            continue
        offered.append(ScoredChunk(chunk=chunks[chunk_id], score=score, matcher="policy", reasons=[RUNNER_UP_REASON]))
        seen.add(chunk_id)
    return offered


def extract_with_llm(
    template: Template,
    assignment: AssignmentResult,
    chunks: Sequence[Chunk],
    sources: Mapping[str, Source],
    job: ExtractionJob,
) -> Extracted:
    """Let the LLM choose the sentences of every content block that has candidates; see the module docstring."""
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    offers = {slot.id: candidates_for(slot.id, assignment, by_id, job.candidates) for slot in template.content_slots()}
    work = [slot for slot in template.content_slots() if offers[slot.id]]
    assigned = {slot_id: list(items) for slot_id, items in assignment.assigned.items()}
    report = ExtractionReport()
    extracted = Extracted(assigned=assigned, selected=set(), report=report)
    if not work:
        return extracted

    def choose(slot: TemplateSlot) -> Selection | LlmSkipped:
        try:
            return job.selector.select(
                slot, offers[slot.id], sources, topic=job.topic, budget=job.budget, deadline=job.deadline
            )
        except Exception as exc:
            # The LLM layer must never break the rule-based path (PLAN.md 4.7): log it, keep the policy's paragraphs.
            log.exception("LLM passage selection for %s failed unexpectedly", slot.id)
            return LlmSkipped(f"unerwarteter Fehler ({type(exc).__name__})")

    with ThreadPoolExecutor(max_workers=max(1, min(job.concurrency, len(work)))) as pool:
        results = list(pool.map(choose, work))
    for slot, result in zip(work, results, strict=True):
        if isinstance(result, Selection):
            assigned[slot.id] = result.excerpts
            extracted.selected.add(slot.id)
            _account(report, slot.id, result)
        else:
            report.fallbacks[slot.id] = result.reason
            _account_skipped(report, result)
    return extracted


def _account(report: ExtractionReport, slot_id: str, selection: Selection) -> None:
    report.slots.append(slot_id)
    if not selection.excerpts:
        report.emptied.append(slot_id)
    report.prompts.add(selection.prompt)
    report.model = selection.model
    report.calls += 1
    report.prompt_tokens += selection.prompt_tokens
    report.completion_tokens += selection.completion_tokens
    report.total_tokens += selection.total_tokens
    report.sentences += selection.sentences
    report.invalid += selection.invalid
    report.cut += selection.cut


def _account_skipped(report: ExtractionReport, skipped: LlmSkipped) -> None:
    report.calls += skipped.calls
    report.prompt_tokens += skipped.prompt_tokens
    report.completion_tokens += skipped.completion_tokens
    report.total_tokens += skipped.total_tokens
