"""Extraction of part 1 (PLAN.md 4.7, D33): which sentences of which paragraphs go into each block.

Rule-based, the policy assigns whole paragraphs to the blocks and the writer takes their first sentences. With
``extraction=llm`` the model chooses the sentences of every content block among candidates: the paragraphs the
policy gave the block, then the next best by the policy's score for that block. The choices run in parallel, one
call per block with candidates. A block whose choice fails (b-api, budget, time, unreadable answer, unexpected
error) keeps the policy's paragraphs, and the reason goes to the audit; a block where no offered paragraph fits
stays empty. A paragraph can be a candidate of several blocks, so the choices are deduplicated in template
order afterwards: a sentence an earlier block prints is dropped from the later one (``deduped``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.concurrency import map_in_threads
from app.domain.models import Chunk, ChunkKind, ScoredChunk, Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, skipped_on_error
from app.llm.deadline import Deadline
from app.llm.usage import Tokens
from app.matching.policy import AssignmentResult
from app.synthesis.citations import without_markers
from app.synthesis.safe_markdown import unescape
from app.synthesis.selection import LENGTH_FACTOR, LlmSelector, Selection, build_excerpts, numbered_sentences
from app.templates.schema import Template, TemplateSlot

RUNNER_UP_REASON = "Kandidat nach Policy-Score"
MIN_SAME_CHARS = 30  # a sentence shorter than this ("Optik.") may stand in a kept block by chance


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
class ExtractionReport(Tokens):
    slots: list[str] = field(default_factory=list)  # blocks whose sentences the LLM chose
    offered: int = 0  # paragraphs offered over all blocks
    emptied: list[str] = field(default_factory=list)  # of those: no offered paragraph fit, the block stays empty
    fallbacks: dict[str, str] = field(default_factory=dict)  # slot id -> why the policy's paragraphs stayed
    prompts: set[str] = field(default_factory=set)
    sentences: int = 0
    invalid: int = 0  # numbers in answers that were not offered
    deduped: int = 0  # chosen sentences an earlier block already prints
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
    kept: Mapping[str, str] | None = None,
) -> Extracted:
    """Let the LLM choose the sentences of every content block that has candidates, but those in ``kept`` (slot id to
    the text it keeps): an earlier text keeps them word for word, and what they print counts as printed, so no block
    made anew prints it a second time (audit 2026-10-03, F13); see the module docstring."""
    kept = kept or {}
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    slots = [slot for slot in template.content_slots() if slot.id not in kept]
    offers = {slot.id: candidates_for(slot.id, assignment, by_id, job.candidates) for slot in slots}
    work = [slot for slot in slots if offers[slot.id]]
    assigned = {slot_id: list(items) for slot_id, items in assignment.assigned.items()}
    report = ExtractionReport()
    extracted = Extracted(assigned=assigned, selected=set(), report=report)
    if not work:
        return extracted

    def choose(slot: TemplateSlot) -> Selection | LlmSkipped:
        return job.selector.select(
            slot, offers[slot.id], sources, topic=job.topic, budget=job.budget, deadline=job.deadline
        )

    # An unexpected error keeps the policy's paragraphs of that block
    guarded = skipped_on_error(choose, lambda slot: f"LLM passage selection for {slot.id}")
    results = map_in_threads(guarded, work, job.concurrency)
    used: set[tuple[str, int]] = set()  # (chunk id, sentence) already printed by an earlier block
    printed = _plain(" ".join(kept.values()))  # what the kept blocks print, in plain words
    for slot, result in zip(work, results, strict=True):
        if isinstance(result, Selection):
            selection = _without_duplicates(result, offers[slot.id], slot, used, printed)
            assigned[slot.id] = selection.excerpts
            extracted.selected.add(slot.id)
            _account(report, slot.id, selection)
        else:
            report.fallbacks[slot.id] = result.reason
            _account_skipped(report, result)
    return extracted


def _without_duplicates(
    selection: Selection,
    candidates: Sequence[ScoredChunk],
    slot: TemplateSlot,
    used: set[tuple[str, int]],
    printed: str = "",
) -> Selection:
    """Drop sentences an earlier block already prints, or a kept block (``printed``, in plain words), and rebuild the
    excerpts; ``used`` grows with the rest."""
    keep = [
        (index, position)
        for index, position in selection.picked
        if _key(candidates, index, position) not in used and not _kept_prints(candidates[index], position, printed)
    ]
    used.update(_key(candidates, index, position) for index, position in keep)
    if len(keep) == len(selection.picked):
        return selection
    excerpts, sentences, cut = build_excerpts(candidates, keep, slot.budget.target_chars * LENGTH_FACTOR)
    return replace(
        selection,
        excerpts=excerpts,
        picked=tuple(keep),
        sentences=sentences,
        cut=selection.cut + cut,
        deduped=len(selection.picked) - len(keep),
    )


def _kept_prints(item: ScoredChunk, position: int, printed: str) -> bool:
    """Whether a kept block prints this sentence already; one too short to tell (``MIN_SAME_CHARS``) counts as not."""
    if not printed:
        return False
    chunk = item.chunk
    sentence = numbered_sentences(chunk)[position] if chunk.kind is ChunkKind.TEXT else chunk.text
    words = _plain(sentence)
    return len(words) >= MIN_SAME_CHARS and words in printed


def _plain(text: str) -> str:
    """Text as words alone: without evidence numbers, markdown escapes and the separators of lists and tables."""
    return " ".join(unescape(without_markers(text)).replace("|", " ").replace("; ", " ").split())


def _key(candidates: Sequence[ScoredChunk], index: int, position: int) -> tuple[str, int]:
    return candidates[index].chunk.chunk_id, position


def _account(report: ExtractionReport, slot_id: str, selection: Selection) -> None:
    report.slots.append(slot_id)
    if not selection.excerpts:
        report.emptied.append(slot_id)
    report.prompts.add(selection.prompt)
    report.model = selection.model
    report.add(selection)
    report.sentences += selection.sentences
    report.offered += selection.offered
    report.invalid += selection.invalid
    report.cut += selection.cut
    report.deduped += selection.deduped


def _account_skipped(report: ExtractionReport, skipped: LlmSkipped) -> None:
    report.add(skipped, skipped.calls)
