"""Question and answer pairs behind POST /api/v2/qa (PLAN.md 8.1, D14; docs/umbau.md U5).

Without an LLM the pairs come from question templates over the sentences of the text: a definition becomes
"Was versteht man unter X?", a year "Was geschah im Jahr …?", an enumeration "Woraus besteht …?" and a purpose
"Wozu dient …?". The answer is the sentence itself, so nothing is invented. With an LLM the model writes the
pairs (one ``Frage;Antwort`` per line) and may spread them over the levels the caller asked for; a failed or
unusable answer falls back to the templates.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.knowledge.node_article import FORMAT_WORDS
from app.knowledge.segmentation import split_sentences
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt

log = logging.getLogger(__name__)

MIN_SENTENCE_CHARS = 30
MAX_FOCUS_TERMS = 12  # keywords of a material named as the focus of the pairs
TOKENS_PER_PAIR = 80
MIN_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS = 300, 3000
_ARTICLES = ("Der ", "Die ", "Das ", "Ein ", "Eine ", "Einer ")
_SUBJECT = r"(?P<subject>[A-ZÄÖÜ][\wäöüß-]*(?:\s+[A-ZÄÖÜ][\wäöüß-]*)?)"
_DEFINITION = re.compile(rf"^{_SUBJECT}\s+(?:ist|sind|bezeichnet|bedeutet|beschreibt|beschreiben)\b")
_PARTS = re.compile(r"^(?P<subject>.{3,60}?)\s+(?:besteht aus|bestehen aus|gliedert sich in|umfasst|umfassen)\b")
_PURPOSE = re.compile(r"^(?P<subject>.{3,60}?)\s+(?P<verb>dient|dienen|ermöglicht|ermöglichen)\b")
_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_NUMBERING = re.compile(r"^\s*(?:\d+\s*[.)]|[a-z]\))\s*")
# German capitalises at a sentence start, so the subject patterns also match adverbs and prepositions there.
# Measured with de_core_news_md on 2026-09-20 (docs/umbau.md U5a): every wrong subject of the live run began
# ADV or ADP, every right one carried a NOUN or PROPN - tagging the subject span alone was enough for all of
# them. Without the model the check is skipped and the endpoint says so.
_NOT_A_SUBJECT_START = frozenset({"ADV", "ADP"})
_NOUNS = frozenset({"NOUN", "PROPN"})


@dataclass(frozen=True)
class QaPair:
    question: str
    answer: str
    level_property: str | None = None
    level_value: str | None = None


def rule_based_pairs(
    text: str,
    *,
    limit: int,
    max_answer_length: int,
    level_property: str | None = None,
    nlp: Callable[[str], Any] | None = None,
) -> list[QaPair]:
    """Pairs from question templates; the answer is the sentence the question was built from.

    ``nlp`` is the spaCy pipeline, when there is one: it decides whether a matched subject really is a noun
    phrase. Without it every template fires as before, which on real text yields questions about adverbs.
    """
    pairs: list[QaPair] = []
    asked: set[str] = set()
    for sentence in split_sentences(" ".join(text.split())):
        if len(sentence) < MIN_SENTENCE_CHARS:
            continue
        question = _question(sentence, nlp)
        if question is None or question in asked:
            continue
        asked.add(question)
        pairs.append(QaPair(question=question, answer=cut(sentence, max_answer_length), level_property=level_property))
        if len(pairs) >= limit:
            break
    return pairs


def _question(sentence: str, nlp: Callable[[str], Any] | None = None) -> str | None:
    definition = _DEFINITION.match(_without_article(sentence))
    if definition and _is_noun_phrase(definition.group("subject"), nlp):
        return f"Was versteht man unter {definition.group('subject')}?"
    parts = _PARTS.match(sentence)
    if parts and _is_noun_phrase(parts.group("subject"), nlp):
        return f"Woraus besteht {_lower_article(parts.group('subject'))}?"
    purpose = _PURPOSE.match(sentence)
    if purpose and _is_noun_phrase(purpose.group("subject"), nlp):
        verb = "dienen" if purpose.group("verb").endswith("en") else "dient"
        return f"Wozu {verb} {_lower_article(purpose.group('subject'))}?"
    year = _YEAR.search(sentence)
    if year:
        return f"Was geschah im Jahr {year.group(1)}?"
    return None


def _is_noun_phrase(subject: str, nlp: Callable[[str], Any] | None) -> bool:
    """Whether the match really names a thing; without the model every match passes, as it did before."""
    if nlp is None:
        return True
    tokens = list(nlp(subject))
    if not tokens or tokens[0].pos_ in _NOT_A_SUBJECT_START:
        return False  # "Daneben sind …", "Als Reduktionsmittel dienen …": the subject comes later
    return any(token.pos_ in _NOUNS for token in tokens)


def _without_article(sentence: str) -> str:
    article = next((a for a in _ARTICLES if sentence.startswith(a)), "")
    return sentence[len(article) :] if article else sentence


def _lower_article(subject: str) -> str:
    """ "Ein Fernrohr" reads better as "ein Fernrohr" inside a question."""
    article = next((a for a in _ARTICLES if subject.startswith(a)), "")
    return f"{article.lower()}{subject[len(article) :]}" if article else subject


def cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class LlmQaWriter:
    """The pairs of the old endpoint, written by the model; ``None`` means: use the templates."""

    def __init__(self, client: BApiClient) -> None:
        self.client = client

    def pairs(
        self,
        text: str,
        *,
        count: int,
        max_answer_length: int,
        budget: RequestBudget,
        level_property: str | None = None,
        level_values: Sequence[str] = (),
        deadline: Deadline | None = None,
        focus_title: str | None = None,
        focus_terms: Sequence[str] = (),
    ) -> list[QaPair] | None:
        """``focus_title`` and ``focus_terms`` name the material of a node and its keywords (D47): the model asks
        about them first, as far as the text treats them."""
        levels = list(level_values) if level_property and level_values else []
        prompt = get_prompt("qa_pairs")
        messages = prompt.render(
            text=text,
            count=count,
            max_answer_length=max_answer_length,
            levels=(
                f"\nStufen ({level_property}): {', '.join(levels)}. Verteile die Paare gleichmäßig über die Stufen "
                "und hänge die Stufe als drittes Feld an."
                if levels
                else ""
            ),
            focus=_focus(focus_title, focus_terms),
        )
        answer = budgeted_chat(
            self.client,
            messages,
            max_output_tokens=min(MAX_OUTPUT_TOKENS, max(MIN_OUTPUT_TOKENS, count * TOKENS_PER_PAIR)),
            budget=budget,
            what="qa",
            deadline=deadline,
        )
        if isinstance(answer, LlmSkipped):
            log.warning("QA pairs from the LLM skipped: %s", answer.reason)
            return None
        pairs = parse_pairs(
            answer.text,
            max_answer_length=max_answer_length,
            level_property=level_property if levels else None,
            level_values=levels,
        )
        return pairs[:count] or None


def _focus(title: str | None, terms: Sequence[str]) -> str:
    """The line that points the model at a material; format words name no subject, so they are left out."""
    if not title:
        return ""
    subjects = [term for term in dict.fromkeys(terms) if term.casefold() not in FORMAT_WORDS][:MAX_FOCUS_TERMS]
    keywords = f" mit den Schlagwörtern {', '.join(subjects)}" if subjects else ""
    return (
        f"\nSchwerpunkt: das Unterrichtsmaterial „{title}“{keywords}. Frage bevorzugt danach, soweit der Text es "
        "behandelt."
    )


def parse_pairs(
    text: str, *, max_answer_length: int, level_property: str | None = None, level_values: Sequence[str] = ()
) -> list[QaPair]:
    """One ``Frage;Antwort[;Stufe]`` per line; lines without a semicolon are dropped, as in the old service."""
    pairs: list[QaPair] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        question = _NUMBERING.sub("", parts[0])
        # An unmappable label stays empty. It used to become level_values[0], which turned a level the
        # model named into one it never named - a wrong label instead of a missing one (docs/umbau.md U5).
        level = _level(parts[2], level_values) if len(parts) > 2 and level_values else None
        pairs.append(
            QaPair(
                question=question,
                answer=cut(parts[1], max_answer_length),
                level_property=level_property,
                level_value=level,
            )
        )
    return pairs


def _level(value: str, level_values: Sequence[str]) -> str | None:
    """The level the model named, mapped onto the levels the caller offered (exact, then contained)."""
    lowered = value.strip().lower()
    for level in level_values:
        if level.lower() == lowered:
            return level
    for level in level_values:
        if level.lower() in lowered or lowered in level.lower():
            return level
    return None
