"""LLM assignment (matcher=llm, D34): the model assigns every paragraph to one content block or to none.

Measured against the gold standard on 2026-09-23 (docs/entwicklung/03-matching.md): macro-F1 0.63 against 0.43 for
hybrid_light with Model2Vec on the same 603 paragraphs, at about 240 tokens per paragraph. On 2026-09-24 batches of
50 paragraphs cut to 400 characters gave 0.72 and 0.69 in two runs on the same 597 paragraphs, 25 and 700 gave 0.66
and 0.73: as good within the spread of the model, at about 177 instead of 241 tokens per paragraph (D36,
docs/entwicklung/messung/mc_llm_sparvarianten.py); sending only the paragraphs the policy is unsure about gave 0.54.
On 2026-10-03 (M59, 583 paragraphs, three runs each) 250 characters held the quality of 400 at 13 % fewer tokens -
macro-F1 0.675 against 0.687, micro-F1 0.796 against 0.794 - and without the model's thinking (reasoning_effort
none) they kept macro-F1 at 0.676 where 400 characters fell to 0.609.

The model sees what a labeller sees: the content blocks with their description, what belongs in them and what does
not, the template's rules for the assignment, and per paragraph the article, its role, the heading path and the text
cut to ``TEXT_CHARS``. It answers per paragraph with a line: the paragraph's id, a block key or "keiner" and a
confidence from 0 to 9 - on 2026-10-08 (M77, four runs on 595 paragraphs) as good as the JSON object of version 2,
at 16 % fewer output tokens and a fifth to a third less time (D93). Batches of
``BATCH_SIZE`` paragraphs run in parallel; a batch the request budget cannot hold next to the others waits for them
to settle (``budgeted_chat``, D39): each reserves about 13,000 tokens and spends about 8,000.

The rule-based assignment runs first and stays the fallback: a paragraph whose batch fails (b-api, budget, time,
unreadable answer) or that the answer leaves out or gives an unknown block keeps the policy's decision, and the
reason goes to the audit. An unreadable answer is asked once more first (M49, V4): in M48 four of 27 runs lost a
batch of 50 paragraphs to one, and since D70 the second question gets a fresh answer - unless the b-api answers
from its store (B_API_RESPONSE_CACHE), then it is not asked. The blocks are cut to their
budgets like the policy's, ordered by the model's confidence.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.concurrency import map_in_threads
from app.domain.models import Chunk, ScoredChunk, Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat, skipped_on_error
from app.llm.client import BApiClient, ChatResult
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.llm.usage import Tokens
from app.matching.policy import LEAD_SCORE, MIN_SCORE, AssignmentResult, cut_to_budgets
from app.templates.schema import Template, block_key

BATCH_SIZE = 50  # paragraphs per call; 50 and 400 characters match 25 and 700 on the gold at 27 % fewer tokens
TEXT_CHARS = 250  # per paragraph: as good as 400 at 13 % fewer tokens, and steadier without thinking (M59)
OUTPUT_TOKENS_PER_PARAGRAPH = 40
NONE_KEY = "keiner"
MATCHER = "llm"
UNKNOWN_BLOCK = "unbekannter Baustein in der Antwort"
LEFT_OUT = "Absatz fehlt in der Antwort"
LEFT_OUT_AT_LIMIT = "Absatz fehlt, die Antwort brach am Ausgabelimit ab (finish_reason=length)"
# A line "p12 fachinhalte 8" (M77); read also as "P12", "**p12**", "- p12", "1. p12" or "p012", with a colon, a comma
# or a pipe between the words, and the confidence as a share, on a scale to 10 or as a percentage (review
# 2026-10-08). An entry opens its line or follows a semicolon or a pipe, so a line holds several and a table row one:
# a remark that names "p1 bis 50" in a sentence is none. ASCII digits only: "²" is a digit to str.isdigit and none to
# int (audit 2026-09-28, KO-25).
_ENTRY_RE = re.compile(
    r"(?:^|[;|])[\s*>•-]*+(?:[0-9]{1,3}[.)]\s+)?\**p([0-9]{1,4})\**[\s:;,=|]+\**([^\s:;,=*|]+)\**[\s:;,=|]+"
    r"([0-9]{1,3}(?:[.,][0-9]+)?)(?![0-9])",
    re.IGNORECASE,
)


@dataclass
class AssignmentJob:
    """What matcher=llm needs: the client, the request budget, the topic and how many calls run at once."""

    client: BApiClient
    budget: RequestBudget
    topic: str
    concurrency: int = 4
    deadline: Deadline | None = None


@dataclass
class LlmAssignmentReport(Tokens):
    paragraphs: int = 0  # paragraphs offered to the model
    answered: int = 0  # of those: the model's decision counts (a block or none)
    fallback: int = 0  # of those: the rule-based decision stays
    fallbacks: dict[str, int] = field(default_factory=dict)  # reason -> paragraphs
    unknown_keys: int = 0  # answers naming a block the template does not have
    asked_again: int = 0  # batches asked once more after an unreadable answer (V4)
    prompts: set[str] = field(default_factory=set)


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
    rules = f"\n\n{template.assignment_rules}" if template.assignment_rules else ""
    # the blocks and the rules are the same for every batch of every topic: in the system message the provider's
    # prompt cache keeps them (D69)
    shared = f"Bausteine:\n{blocks}{rules}"
    return get_prompt("paragraph_assignment").sharing(shared).render(topic=topic, paragraphs=paragraphs)


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
    """Block key and confidence per paragraph id; ``None`` when the answer holds neither lines nor a JSON object.

    A line ``p12 fachinhalte 8`` gives paragraph, block and confidence (``_ENTRY_RE``). An answer without such a line
    is read as the JSON object of version 2, which a model may still give. Keys are compared in lower case; a line or
    an entry of another shape is skipped.
    """
    parsed: dict[str, tuple[str, float]] = {}
    for line in text.splitlines():
        for found in _ENTRY_RE.finditer(line):
            number, key, confidence = found.groups()
            parsed[f"p{int(number)}"] = (block_key(key), _confidence(confidence))
    return parsed or _parse_object(text)


def _confidence(written: str) -> float:
    """The confidence of a line as the model wrote it: a digit of the scale the prompt asks for, 0 to 9; a share like
    0.8 or 0,8; 10 as the top of a scale to 10; a larger number as a percentage."""
    value = float(written.replace(",", "."))
    if "." in written or "," in written:
        return min(1.0, value)
    if value <= 9:
        return value / 9
    return 1.0 if value == 10 else min(1.0, value / 100)


def _parse_object(text: str) -> dict[str, tuple[str, float]] | None:
    """The JSON object of version 2: ``{"p1": ["fachinhalte", 0.8]}``; ``None`` when the answer holds none.

    A confidence outside 0 to 1 is clipped, an entry of another shape is skipped.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except (ValueError, RecursionError):  # also a number of over 4,300 digits and a nesting too deep to read
        return None
    if not isinstance(data, dict):
        return None
    parsed: dict[str, tuple[str, float]] = {}
    for alias, value in data.items():
        if not (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)):
            continue
        try:
            confidence = float(value[1])
        except (TypeError, ValueError, OverflowError):  # an integer of 400 digits is no float
            continue
        parsed[str(alias)] = (block_key(value[0]), min(1.0, max(0.0, confidence)))
    return parsed


def assign_with_llm(
    template: Template,
    chunks: Sequence[Chunk],
    sources: Mapping[str, Source],
    rule_based: AssignmentResult,
    job: AssignmentJob,
) -> tuple[AssignmentResult, LlmAssignmentReport]:
    """Let the model assign the paragraphs; see the module docstring. Without a single answer: ``rule_based``."""
    generated = template.generated_keys()
    offered = [chunk for chunk in chunks if chunk.lexicon_slot not in generated]  # the policy skips those too
    batches = [offered[i : i + BATCH_SIZE] for i in range(0, len(offered), BATCH_SIZE)]
    report = LlmAssignmentReport(paragraphs=len(offered))
    if not batches:
        return rule_based, report

    def ask_once(batch: Sequence[Chunk]) -> ChatResult | LlmSkipped:
        return budgeted_chat(
            job.client,
            render_messages(template, job.topic, batch, sources),
            max_output_tokens=OUTPUT_TOKENS_PER_PARAGRAPH * len(batch),
            budget=job.budget,
            what="Zuordnung",
            prompt="paragraph_assignment",
            deadline=job.deadline,
        )

    def ask(batch: Sequence[Chunk]) -> list[ChatResult | LlmSkipped]:
        first = ask_once(batch)
        # an unreadable answer once more (V4), unless the b-api's store would give it again (B_API_RESPONSE_CACHE)
        if isinstance(first, LlmSkipped) or parse_assignment(first.text) is not None or job.client.response_cache:
            return [first]
        return [first, ask_once(batch)]

    # An unexpected error keeps the policy's decision for that batch
    answers = map_in_threads(skipped_on_error(ask, lambda batch: "LLM assignment of a batch"), batches, job.concurrency)

    key_to_id = {block_key(slot.slot): slot.id for slot in template.content_slots()}
    decided: dict[str, tuple[str | None, float]] = {}  # chunk id -> (slot id or None for "keiner", confidence)
    fallbacks: Counter[str] = Counter()
    for batch, attempts in zip(batches, answers, strict=True):
        tried = attempts if isinstance(attempts, list) else [attempts]  # an unexpected error is one LlmSkipped
        for attempt in tried:
            _account(report, attempt)
            if isinstance(attempt, ChatResult):  # a call that answered, even unreadably, names prompt and model
                report.prompts.add(get_prompt("paragraph_assignment").tag)
                report.model = attempt.model
        # a second question the budget or the time turned away before any call is none
        report.asked_again += sum(1 for again in tried[1:] if not isinstance(again, LlmSkipped) or again.calls)
        answer = tried[-1]
        if isinstance(answer, LlmSkipped):
            fallbacks[answer.reason] += len(batch)
            continue
        parsed = parse_assignment(answer.text)
        if parsed is None:
            reason = f"unlesbare Antwort des Modells (finish_reason={answer.finish_reason or 'unbekannt'})"
            fallbacks[reason] += len(batch)
            continue
        for number, chunk in enumerate(batch, start=1):
            entry = parsed.get(f"p{number}")
            if entry is None:  # an answer the output limit cut says so, for LLM_MAX_TOKENS and the reasoning effort
                fallbacks[LEFT_OUT_AT_LIMIT if answer.finish_reason == "length" else LEFT_OUT] += 1
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
            # The policy scores up to LEAD_SCORE, the model to 1: on one scale a paragraph the rules kept, because its
            # batch failed, no longer pushes out what the model chose; among themselves they keep their order (KO-12)
            score = rule_based.slot_scores.get(slot_id, {}).get(chunk.chunk_id, MIN_SCORE) / LEAD_SCORE
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
    report.add(answer, answer.calls if isinstance(answer, LlmSkipped) else 1)
