"""The LLM check of part 2 (curriculum_check=llm, D58): the model rates every curriculum element the rules found.

M22 found about 60 % of what part 2 prints fitting its topic and 13 to 19 % not fitting: a keyword inside another word
or meaning something else, and elements only their heading names. The model reads what a teacher would read - the
element, the area it stands under and its curriculum - and rates each with the notes of M22: 2 fits, 1 touches the
topic, 0 does not fit. A 0 leaves part 2; a heading-only element rated 2 stands on its own instead of being counted
with its area (``render._bundled``).

The rules decide first and stay the fallback: an element whose batch fails (b-api, budget, time, unreadable answer) or
that the answer leaves out keeps its place unrated, and the reason goes to the audit. Batches of ``BATCH_SIZE``
elements run in parallel, as the batches of the LLM assignment do (app/matching/llm_assignment.py).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any

from app.knowledge.article_choice import UNREADABLE, Usage, read_number, read_object
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient, ChatResult
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.sources.lehrplan.matcher import CurriculumMatch

log = logging.getLogger(__name__)

BATCH_SIZE = 60  # elements per call: about 2,700 tokens of listing
ELEMENT_CHARS = 300  # an element is cut beyond this; nine in ten of the cache are shorter than 201 characters
OUTPUT_TOKENS_PER_ELEMENT = 12  # as the hit check of the side articles, measured with gpt-6-luna (M25)
NOTES = (0, 1, 2)
LEFT_OUT = "Element fehlt in der Antwort"


@dataclass
class CurriculumCheckJob:
    """What the check needs: the client, the request budget, the topic and its subjects, and how many calls at once."""

    client: BApiClient
    budget: RequestBudget
    topic: str
    subjects: Sequence[str] = ()
    concurrency: int = 4
    deadline: Deadline | None = None


@dataclass
class CurriculumCheckReport(Usage):
    rated: int = 0  # elements offered to the model
    answered: int = 0  # elements the model gave a note of 0, 1 or 2
    dropped: int = 0  # elements rated 0, gone from part 2
    fallbacks: dict[str, int] = field(default_factory=dict)  # elements left unrated, by reason


def check_curriculum(
    job: CurriculumCheckJob, matches: Sequence[CurriculumMatch]
) -> tuple[list[CurriculumMatch], CurriculumCheckReport]:
    """The elements the model does not rate 0, in their order and with their note; see the module docstring."""
    report = CurriculumCheckReport(rated=len(matches))
    batches = [list(matches[start : start + BATCH_SIZE]) for start in range(0, len(matches), BATCH_SIZE)]
    if not batches:
        return [], report
    prompt = get_prompt("curriculum_check")
    topic = f"{job.topic} (Fach: {', '.join(job.subjects)})" if job.subjects else job.topic

    def ask(batch: Sequence[CurriculumMatch]) -> ChatResult | LlmSkipped:
        try:
            return budgeted_chat(
                job.client,
                prompt.render(topic=topic, elements=_listing(batch)),
                max_output_tokens=OUTPUT_TOKENS_PER_ELEMENT * len(batch),
                budget=job.budget,
                what="Lehrplanprüfung",
                deadline=job.deadline,
            )
        except Exception as exc:
            # The LLM layer must never break the rule-based path (PLAN.md 4.7): log it, keep the rules' elements.
            log.exception("LLM check of a batch of curriculum elements failed unexpectedly")
            return LlmSkipped(f"unerwarteter Fehler ({type(exc).__name__})")

    with ThreadPoolExecutor(max_workers=max(1, min(job.concurrency, len(batches)))) as pool:
        answers = list(pool.map(ask, batches))

    notes: dict[int, int] = {}  # position in ``matches`` -> the model's note
    fallbacks: Counter[str] = Counter()
    start = 0
    for batch, answer in zip(batches, answers, strict=True):
        report.count(answer, prompt.tag)
        read = _read(answer)
        if isinstance(read, str):
            fallbacks[read] += len(batch)
        else:
            for number in range(1, len(batch) + 1):
                note = read_number(read.get(f"e{number}"))
                if note in NOTES:
                    notes[start + number - 1] = note
                else:
                    fallbacks[LEFT_OUT] += 1
        start += len(batch)

    kept: list[CurriculumMatch] = []
    for position, match in enumerate(matches):
        note = notes.get(position)
        if note == 0:
            report.dropped += 1
        else:
            kept.append(match if note is None else replace(match, note=note))
    report.answered = len(notes)
    report.fallbacks = dict(fallbacks)
    return kept, report


def _listing(batch: Sequence[CurriculumMatch]) -> str:
    lines = []
    for number, match in enumerate(batch, start=1):
        label = " ".join(match.hit.label.split())
        if len(label) > ELEMENT_CHARS:
            label = label[:ELEMENT_CHARS].rstrip() + "…"
        line = f"e{number}: „{label}“"
        if match.hit.parent_label:
            line += f" · Bereich: {' '.join(match.hit.parent_label.split())}"
        lines.append(f"{line} · Lehrplan: {match.hit.lehrplan.label}")
    return "\n".join(lines)


def _read(answer: ChatResult | LlmSkipped) -> dict[str, Any] | str:
    """The model's notes by element id, or the reason there are none."""
    if isinstance(answer, LlmSkipped):
        return answer.reason
    notes = read_object(answer.text)
    return UNREADABLE if notes is None else notes
