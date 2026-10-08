"""The topic a writing profile writes about (D72): the topic as asked, or the model's wording of a text in its place.

Jan, 2026-10-02: "wenn das thema zu lang ist oder eine texteingabe war sollte in den beiden profilen die ki das thema
passend zum input formulieren" - and a node, a material or a collection, can stand in for the topic or come with it.
A topic stands as asked while it reads as one: the 123 topics the project knows (the gold queries of the article
choice, the group and mixed topics of M37, those of M48) have at most five words and 37 characters and no question or
exclamation mark. Longer than six words or 60 characters, or with a sentence's punctuation, it is a text, and so are
the metadata of a node without a topic; then the model words the topic, close to the input and with its aspect, the
node beside a topic showing how the topic is meant. Whatever keeps the model from wording one - b-api, budget, time,
an unreadable answer, one longer than a topic - leaves the topic of before, and the reason goes to the audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob, read_object
from app.knowledge.collection_context import is_neutral
from app.knowledge.node_article import PROMPT_CHARS, TITLE_CHARS
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.prompts import get_prompt
from app.llm.usage import Usage

MAX_WORDS = 6  # a topic of the project has at most five
MAX_CHARS = 60  # and at most 37 characters
ANSWER_WORDS = 12  # the prompt asks for eight at most; more is a sentence, not a topic
ANSWER_CHARS = 100
OUTPUT_TOKENS = 60  # one short title; the reasoning room of the model comes on top (budgeted_chat)
LONG = "länger als ein Thema"
SENTENCE = "ein Satz oder eine Frage"
METADATA = "Metadaten eines Knotens ohne Thema"
TOO_LONG_ANSWER = "Antwort länger als ein Thema"
NEUTRAL_ANSWER = "Antwort nennt keinen Gegenstand"
# A question, an exclamation, or a word of two lower-case letters or more ending a sentence: "funktioniert." - not an
# ordinal ("19. Jahrhundert") and not an abbreviation of one ("St. Petersburg", "Dr. Faustus")
_SENTENCE = re.compile(r"[?!]|[a-zäöüß]{2}\.(?:\s+[A-ZÄÖÜ]|\s*$)")
_QUOTES = " \t\n\"'„“”‚‘’«»"


class Metadata(Protocol):
    """What a node (``NodeInfo``) or the collection of part 3 (``CollectionInfo``) says about its topic."""

    @property
    def title(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def keywords(self) -> tuple[str, ...]: ...
    @property
    def subject_labels(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class WordingRequest:
    """What the model is to word: where the input came from, why, and the input as the model hears it."""

    source: str  # "Thema", "Material", "Sammlung", "Thema mit Material", "Thema mit Sammlung"
    reason: str  # LONG, SENTENCE or METADATA
    text: str


@dataclass
class TopicWordingReport(Usage):
    """What the model was asked to word and what it answered, for the audit."""

    source: str = ""
    reason: str = ""
    topic: str | None = None  # the model's wording; None when it gave none
    fallback: str | None = None  # why the topic stayed as before


def needs_wording(topic: str) -> str | None:
    """Why ``topic`` reads as a text rather than a topic - ``SENTENCE`` or ``LONG`` -, or ``None``."""
    text = " ".join(topic.split())
    if _SENTENCE.search(text):
        return SENTENCE
    if len(text.split()) > MAX_WORDS or len(text) > MAX_CHARS:
        return LONG
    return None


def _kind(info: Metadata) -> str:
    return "material" if getattr(info, "kind", "collection") == "material" else "collection"


def metadata_input(info: Metadata) -> str:
    """The metadata of a node or a collection as the model hears them, cut as for the material's article (D47)."""
    label = "des Materials" if _kind(info) == "material" else "der Sammlung"
    return (
        f"Titel {label}: {info.title[:TITLE_CHARS]}\n"
        f"Fächer: {', '.join(info.subject_labels) or 'keine'}\n"
        f"Schlagwörter: {', '.join(info.keywords)[:PROMPT_CHARS] or 'keine'}\n"
        f"Beschreibung: {info.description[:PROMPT_CHARS] or 'keine'}"
    )


def wording_request(topic: str | None, beside: Metadata | None, place: str = "") -> WordingRequest | None:
    """What a writing profile lets the model word, or ``None`` where the topic stands as asked.

    ``beside`` is the node of the request or, without one, the collection of part 3: it stands in for a missing topic
    and shows how a topic that is a text is meant. ``place`` is where such a collection stands in its topic tree
    (``collection_context.describe``); the model hears it after the metadata, which made its wording fit better
    (M71: 3.8 instead of 3.4-3.5 of 5 for neutral titles, 4.7 instead of 4.4 for titles naming their subject matter).
    """
    noun = None if beside is None else ("Material" if _kind(beside) == "material" else "Sammlung")
    if topic:
        reason = needs_wording(topic)
        if reason is None:
            return None
        text = f"Anfrage der Lehrkraft: {' '.join(topic.split())}"
        if beside is None:
            return WordingRequest(source="Thema", reason=reason, text=text)
        return WordingRequest(
            source=f"Thema mit {noun}", reason=reason, text=f"{text}\n\nDazu angegeben:\n{metadata_input(beside)}"
        )
    if beside is None or noun is None:
        return None
    text = metadata_input(beside) + (f"\nLage im Themenbaum: {place}" if place else "")
    return WordingRequest(source=noun, reason=METADATA, text=text)


def word_topic(job: ArticleChoiceJob, text: str, report: TopicWordingReport) -> str | None:
    """The model's wording of the topic of ``text``; ``None`` when it gave none, and ``report`` says why."""
    prompt = get_prompt("topic_wording")
    answer = budgeted_chat(
        job.client,
        prompt.render(input=text),
        max_output_tokens=OUTPUT_TOKENS,
        budget=job.budget,
        what="Thema der Anfrage",
        prompt=prompt.id,
        deadline=job.deadline,
        caller_text=text,
    )
    report.count(answer, prompt.tag)
    if isinstance(answer, LlmSkipped):
        report.fallback = answer.reason
        return None
    data = read_object(answer.text)
    worded = data.get("thema") if data is not None else None
    if not isinstance(worded, str) or not worded.strip(_QUOTES):
        report.fallback = UNREADABLE
        return None
    worded = " ".join(worded.strip(_QUOTES).split())
    if len(worded.split()) > ANSWER_WORDS or len(worded) > ANSWER_CHARS:
        report.fallback = TOO_LONG_ANSWER
        return None
    if is_neutral(worded):  # "Anwendungen" for a collection of that name: the topic of before says more (M71)
        report.fallback = NEUTRAL_ANSWER
        return None
    report.topic = worded
    return worded
