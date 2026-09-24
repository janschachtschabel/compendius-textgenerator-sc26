"""LLM assignment (matcher=llm, D34): the model assigns every paragraph to one content block or to none.

Measured against the gold standard on 2026-09-23 (docs/entwicklung/03-matching.md): macro-F1 0.63 against 0.43 for
hybrid_light with Model2Vec on the same 603 paragraphs, at about 240 tokens per paragraph. On 2026-09-24 batches of
50 paragraphs cut to 400 characters gave 0.72 and 0.69 in two runs on the same 597 paragraphs, 25 and 700 gave 0.66
and 0.73: as good within the spread of the model, at about 177 instead of 241 tokens per paragraph (D36,
docs/entwicklung/messung/mc_llm_sparvarianten.py); sending only the paragraphs the policy is unsure about gave 0.54.

The model sees what a labeller sees: the content blocks with their description, what belongs in them and what does
not, the template's rules for the assignment, and per paragraph the article, its role, the heading path and the text
cut to ``TEXT_CHARS``. It answers per paragraph with a block key or "keiner" and a confidence. Batches of
``BATCH_SIZE`` paragraphs run in parallel.

The rule-based assignment runs first and stays the fallback: a paragraph whose batch fails (b-api, budget, time,
unreadable answer) or that the answer leaves out or gives an unknown block keeps the policy's decision, and the
reason goes to the audit. The blocks are cut to their budgets like the policy's, ordered by the model's confidence.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.domain.models import Chunk, ScoredChunk, Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient, ChatResult
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.matching.policy import MIN_SCORE, AssignmentResult, cut_to_budgets
from app.templates.schema import Template

log = logging.getLogger(__name__)

BATCH_SIZE = 50  # paragraphs per call; 50 and 400 characters match 25 and 700 on the gold at 27 % fewer tokens
TEXT_CHARS = 400  # per paragraph, as in the measurement of 2026-09-24
OUTPUT_TOKENS_PER_PARAGRAPH = 40
NONE_KEY = "keiner"
MATCHER = "llm"
UNKNOWN_BLOCK = "unbekannter Baustein in der Antwort"
LEFT_OUT = "Absatz fehlt in der Antwort"


@dataclass
class AssignmentJob:
    """What matcher=llm needs: the client, the request budget, the topic and how many calls run at once."""

    client: BApiClient
    budget: RequestBudget
    topic: str
    concurrency: int = 4
    deadline: Deadline | None = None


@dataclass
class LlmAssignmentReport:
    paragraphs: int = 0  # paragraphs offered to the model
    answered: int = 0  # of those: the model's decision counts (a block or none)
    fallback: int = 0  # of those: the rule-based decision stays
    fallbacks: dict[str, int] = field(default_factory=dict)  # reason -> paragraphs
    unknown_keys: int = 0  # answers naming a block the template does not have
    prompts: set[str] = field(default_factory=set)
    model: str | None = None
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


def render_messages(
    template: Template, topic: str, chunks: Sequence[Chunk], sources: Mapping[str, Source]
) -> list[dict[str, str]]:
    """The request for one batch; the paragraphs are numbered p1, p2, ... in the order of ``chunks``."""
    blocks = "\n".join(
        f"- {slot.slot} ({slot.title}): {slot.description} Gehört hinein: {slot.inclusions} "
        f"Gehört nicht hinein: {slot.exclusions}"
        for slot in template.content_slots()
    )
    paragraphs = "\n\n".join(
        f"p{number} (Artikel: {_title(chunk, sources)}, {_role(chunk, sources)}; Abschnitt: {chunk.full_heading}):\n"
        f"{' '.join(chunk.text.split())[:TEXT_CHARS]}"
        for number, chunk in enumerate(chunks, start=1)
    )
    rules = f"{template.assignment_rules}\n\n" if template.assignment_rules else ""
    return get_prompt("paragraph_assignment").render(topic=topic, blocks=blocks, rules=rules, paragraphs=paragraphs)


def _title(chunk: Chunk, sources: Mapping[str, Source]) -> str:
    source = sources.get(chunk.source_id)
    return source.title if source is not None else chunk.source_id


def _role(chunk: Chunk, sources: Mapping[str, Source]) -> str:
    source = sources.get(chunk.source_id)
    if source is not None and source.is_primary:
        return "Hauptartikel"
    if source is not None and source.origin == "same_topic":
        return f"dasselbe Thema aus {source.project}"
    return "weiterer Artikel"


def parse_assignment(text: str) -> dict[str, tuple[str, float]] | None:
    """Block key and confidence per paragraph id; ``None`` when the answer holds no JSON object.

    Keys are compared in lower case; a confidence outside 0 to 1 is clipped, an entry of another shape is skipped.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    parsed: dict[str, tuple[str, float]] = {}
    for alias, value in data.items():
        if not (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)):
            continue
        try:
            confidence = float(value[1])
        except (TypeError, ValueError):
            continue
        parsed[str(alias)] = (value[0].strip().lower(), min(1.0, max(0.0, confidence)))
    return parsed


def assign_with_llm(
    template: Template,
    chunks: Sequence[Chunk],
    sources: Mapping[str, Source],
    rule_based: AssignmentResult,
    job: AssignmentJob,
) -> tuple[AssignmentResult, LlmAssignmentReport]:
    """Let the model assign the paragraphs; see the module docstring. Without a single answer: ``rule_based``."""
    generated = {slot.slot for slot in template.slots if slot.is_generated}
    offered = [chunk for chunk in chunks if chunk.lexicon_slot not in generated]  # the policy skips those too
    batches = [offered[i : i + BATCH_SIZE] for i in range(0, len(offered), BATCH_SIZE)]
    report = LlmAssignmentReport(paragraphs=len(offered))
    if not batches:
        return rule_based, report

    def ask(batch: Sequence[Chunk]) -> ChatResult | LlmSkipped:
        try:
            return budgeted_chat(
                job.client,
                render_messages(template, job.topic, batch, sources),
                max_output_tokens=OUTPUT_TOKENS_PER_PARAGRAPH * len(batch),
                budget=job.budget,
                what="Zuordnung",
                deadline=job.deadline,
            )
        except Exception as exc:
            # The LLM layer must never break the rule-based path (PLAN.md 4.7): log it, keep the policy's decision.
            log.exception("LLM assignment of a batch failed unexpectedly")
            return LlmSkipped(f"unerwarteter Fehler ({type(exc).__name__})")

    with ThreadPoolExecutor(max_workers=max(1, min(job.concurrency, len(batches)))) as pool:
        answers = list(pool.map(ask, batches))

    key_to_id = {slot.slot: slot.id for slot in template.content_slots()}
    decided: dict[str, tuple[str | None, float]] = {}  # chunk id -> (slot id or None for "keiner", confidence)
    fallbacks: Counter[str] = Counter()
    for batch, answer in zip(batches, answers, strict=True):
        if isinstance(answer, LlmSkipped):
            _account(report, answer)
            fallbacks[answer.reason] += len(batch)
            continue
        _account(report, answer)
        report.prompts.add(get_prompt("paragraph_assignment").tag)
        report.model = answer.model
        parsed = parse_assignment(answer.text)
        if parsed is None:
            reason = f"unlesbare Antwort des Modells (finish_reason={answer.finish_reason or 'unbekannt'})"
            fallbacks[reason] += len(batch)
            continue
        for number, chunk in enumerate(batch, start=1):
            entry = parsed.get(f"p{number}")
            if entry is None:
                fallbacks[LEFT_OUT] += 1
            elif entry[0] == NONE_KEY:
                decided[chunk.chunk_id] = (None, entry[1])
            elif entry[0] in key_to_id:
                decided[chunk.chunk_id] = (key_to_id[entry[0]], entry[1])
            else:
                report.unknown_keys += 1
                fallbacks[UNKNOWN_BLOCK] += 1

    report.answered = len(decided)
    report.fallback = report.paragraphs - report.answered
    report.fallbacks = dict(fallbacks)
    if not decided:
        return rule_based, report
    return _combine(template, offered, decided, rule_based, skipped=len(chunks) - len(offered)), report


def _combine(
    template: Template,
    offered: Sequence[Chunk],
    decided: Mapping[str, tuple[str | None, float]],
    rule_based: AssignmentResult,
    skipped: int,
) -> AssignmentResult:
    """The model's decisions, the policy's where the model gave none, cut to the budgets of the blocks.

    ``skipped`` counts the chunks nobody assigns (material of generated blocks); like the policy, the result counts
    them as unassigned.
    """
    per_slot: dict[str, list[ScoredChunk]] = {slot.id: [] for slot in template.slots}
    classified: dict[str, str] = {}
    for chunk in offered:
        if chunk.chunk_id in decided:
            slot_id, confidence = decided[chunk.chunk_id]
            if slot_id is None:
                continue
            reason = f"LLM-Zuordnung (Sicherheit {confidence:.2f})"
            per_slot[slot_id].append(ScoredChunk(chunk=chunk, score=confidence, matcher=MATCHER, reasons=[reason]))
        else:
            fallback_slot = rule_based.classified.get(chunk.chunk_id)
            if fallback_slot is None:
                continue
            slot_id = fallback_slot
            score = rule_based.slot_scores.get(slot_id, {}).get(chunk.chunk_id, MIN_SCORE)
            reason = "Regelzuordnung: das LLM hat für diesen Absatz nicht entschieden"
            per_slot[slot_id].append(ScoredChunk(chunk=chunk, score=score, matcher="policy", reasons=[reason]))
        classified[chunk.chunk_id] = slot_id
    kept, notes, dropped = cut_to_budgets(template, per_slot)
    return AssignmentResult(
        assigned=kept,
        unassigned=skipped + len(offered) - len(classified) + dropped,
        notes=notes,
        classified=classified,
        slot_scores=rule_based.slot_scores,  # the candidates extraction=llm offers after the chosen paragraphs
    )


def _account(report: LlmAssignmentReport, answer: ChatResult | LlmSkipped) -> None:
    report.calls += answer.calls if isinstance(answer, LlmSkipped) else 1
    report.prompt_tokens += answer.prompt_tokens
    report.completion_tokens += answer.completion_tokens
    report.total_tokens += answer.total_tokens
