"""The check of model knowledge (07, point 12a): a second call per written block reads its sentences of model knowledge
again and strikes or corrects what it holds for wrong.

In M48 six of the eight light errors of best-coverage-generated - dates, bodies, attributions - stood in sentences of
model knowledge, and only the cited rest of a text is checked against its sources. The check reads the block as context
and answers per sentence: "ok", "streichen", or the sentence corrected. A corrected sentence is model knowledge still
and keeps its mark; one far longer than before is no correction - the check does not write the block anew. Whatever
keeps the model from answering - b-api, budget, time, an unreadable answer - leaves the block as written, and the
reason goes to the audit.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field, replace

from app.knowledge.article_choice import UNREADABLE, read_object
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.llm.usage import Usage
from app.synthesis.citations import (
    MODEL_KNOWLEDGE_LABEL,
    MODEL_KNOWLEDGE_OPEN,
    collapse,
    marked_sentence,
    neutralize,
    without_markers,
)
from app.synthesis.facets import END_MARKER
from app.synthesis.llm import LlmSection
from app.synthesis.safe_markdown import unescape

# A verdict is a word of its own: "ok, stimmt" keeps, "Streichen: falsch" strikes, "Oktober 1889 …" is a sentence
_KEEP_RE = re.compile(r"^ok\b", re.IGNORECASE)
_STRIKE_RE = re.compile(r"^streichen\b", re.IGNORECASE)
ALL_STRUCK = "die Prüfung des Modellwissens strich jeden Satz"
MIN_OUTPUT_TOKENS = 200
OUTPUT_TOKENS_PER_SENTENCE = 80  # room for a corrected sentence; "ok" takes a few
MAX_OUTPUT_TOKENS = 4000
# A correction mends a date or a name: twice as long as its sentence and this much more at most, and like it - the
# corrections of M53 were 0.66 to 1.0 alike their sentences, a verdict in other words ("korrekt") 0.25 at most
LONGER, LONGER_CHARS = 2, 100
MIN_SIMILARITY = 0.5
_SPAN_RE = re.compile(re.escape(MODEL_KNOWLEDGE_OPEN) + r"(.*?)" + re.escape(END_MARKER), re.DOTALL)


@dataclass
class CheckOutcome(Usage):
    """What the check did to one block, with the cost of its call; ``fallback`` says why it stayed unchecked."""

    checked: int = 0
    struck: int = 0
    corrected: int = 0
    fallback: str | None = None


@dataclass
class ModelKnowledgeCheckReport(Usage):
    """The check over a compendium, for the audit."""

    sections: list[str] = field(default_factory=list)  # blocks whose sentences the model checked
    checked: int = 0
    struck: int = 0
    corrected: int = 0
    fallbacks: dict[str, str] = field(default_factory=dict)  # slot id -> why its sentences stayed unchecked

    def take(self, slot_id: str, outcome: CheckOutcome) -> None:
        self.add(outcome, outcome.calls)
        self.model = outcome.model or self.model
        self.prompts = sorted({*self.prompts, *outcome.prompts})
        self.checked += outcome.checked
        self.struck += outcome.struck
        self.corrected += outcome.corrected
        if outcome.fallback is not None:
            self.fallbacks[slot_id] = outcome.fallback
        elif outcome.checked:
            self.sections.append(slot_id)


def check_section(
    client: BApiClient,
    section: LlmSection,
    *,
    topic: str,
    title: str,
    budget: RequestBudget,
    deadline: Deadline | None = None,
) -> tuple[LlmSection, CheckOutcome]:
    """``section`` with its sentences of model knowledge checked, and what the check did; a block without such
    sentences makes no call. The text may come back empty: then the block was model knowledge alone, all struck."""
    outcome = CheckOutcome()
    spans = list(_SPAN_RE.finditer(section.text))
    if not spans:
        return section, outcome
    sentences = [_plain(span.group(1)) for span in spans]
    prompt = get_prompt("model_knowledge_check")
    listing = "\n".join(f"{number}. {sentence}" for number, sentence in enumerate(sentences, start=1))
    answer = budgeted_chat(
        client,
        prompt.render(topic=topic, title=title, block=_readable(section.text), sentences=listing),
        max_output_tokens=min(MAX_OUTPUT_TOKENS, MIN_OUTPUT_TOKENS + OUTPUT_TOKENS_PER_SENTENCE * len(spans)),
        budget=budget,
        what=f"Prüfung des Modellwissens in {title}",
        prompt=prompt.id,
        deadline=deadline,
    )
    outcome.count(answer, prompt.tag)
    if isinstance(answer, LlmSkipped):
        outcome.fallback = answer.reason
        return section, outcome
    verdicts = read_object(answer.text)
    if verdicts is None:
        outcome.fallback = f"{UNREADABLE} (finish_reason={answer.finish_reason or 'unbekannt'})"
        return section, outcome
    outcome.checked = len(spans)
    pieces: list[str] = []
    position = 0
    for number, (span, sentence) in enumerate(zip(spans, sentences, strict=True), start=1):
        pieces.append(section.text[position : span.start()])
        position = span.end()
        verdict = verdicts.get(str(number))
        if isinstance(verdict, str) and _STRIKE_RE.match(verdict.strip()):
            outcome.struck += 1
            continue
        corrected = _correction(verdict, sentence)
        outcome.corrected += corrected is not None
        pieces.append(span.group(0) if corrected is None else marked_sentence(corrected))
    pieces.append(section.text[position:])
    if not (outcome.struck or outcome.corrected):
        return section, outcome
    text = _tidy("".join(pieces))
    return replace(section, text=text, marked_sentences=section.marked_sentences - outcome.struck), outcome


def _correction(verdict: object, sentence: str) -> str | None:
    """The sentence as the check corrected it, without links, tags and addresses as every written sentence - or
    ``None``: "ok" or a verdict in other words, no text, the sentence again, a question (D60), or one far longer or
    too unlike it."""
    if not isinstance(verdict, str):
        return None
    corrected = neutralize(verdict)
    if not corrected or _KEEP_RE.match(corrected) or corrected == sentence or corrected.rstrip(" )").endswith("?"):
        return None
    if len(corrected) > LONGER * len(sentence) + LONGER_CHARS:
        return None
    return corrected if difflib.SequenceMatcher(None, sentence, corrected).ratio() >= MIN_SIMILARITY else None


def _plain(marked: str) -> str:
    """A marked sentence as the model reads it: without its label, its escapes undone."""
    return collapse(unescape(marked.replace(MODEL_KNOWLEDGE_LABEL, "")))


def _readable(text: str) -> str:
    """The block as context: without numbers, labels and comments, its escapes undone."""
    return unescape(neutralize(without_markers(text)))


def _tidy(text: str) -> str:
    """The block after the check: no doubled blank where a sentence went, no paragraph left empty."""
    paragraphs = (re.sub(r"[ \t]{2,}", " ", paragraph).strip() for paragraph in text.split("\n\n"))
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
