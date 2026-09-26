"""The LLM ways of /entities (D62): the model names the entities of a text, and it checks the links.

Both measured on the texts of 40 materials against two blind raters (docs/entwicklung, M36, gpt-6-luna):

- Naming: the model names the persons, places, organisations, works, events and subject terms of the text, each with
  the word as it stands and the title of its article. F1 0.78 against 0.38 for spaCy and the dictionary of titles
  (precision 0.70 against 0.29), at about 800 tokens and 4 s per text. Every word it named stood in the text, so an
  entity keeps its place: the first where the word stands as a whole word, else the first inside a longer one.
- Checking: the model grades every link in one call - 2 an entity or term the text is about and the article means
  it, 1 fitting but minor or an everyday word, 0 something else. Keeping only the 2s raised the precision of the
  named entities to 0.94 but dropped a third of the fitting ones, F1 0.76 (measured through the endpoint, D62; the
  prototype of M36, which saw every link of a text, gave 0.91 and 0.80). So the endpoint only checks when asked to.

Whatever keeps the model from answering usably - b-api, budget, time, an unreadable answer - comes back as ``None``
with the reason in the report: the endpoint then lets the rules decide and says so.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from app.knowledge.article_choice import Usage, read_number, read_object
from app.knowledge.recognise import Mention
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient, ChatResult
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt

EXTRACTION_OUTPUT_TOKENS = 1200  # as measured in M36, where a text of a material named about eight entities
EXTRACTION_TOKENS_PER_ENTITY = 24  # 1,200 for the default of 50 entities; a caller who wants more gets more room
CHECK_OUTPUT_TOKENS_PER_LINK = 20
CHECK_OUTPUT_TOKENS = 200
LEAD_CHARS = 180  # what the check sees of an article, as the hit check of the article choice
MAX_WORD_CHARS = 100  # a longer "word" is no name, and every search for it costs time in its length
MAX_TRIES = 200  # places of one word looked at, per spelling
GRADES = frozenset({0, 1, 2})
UNREADABLE = "Antwort nicht lesbar"
CUT_OFF = "Antwort vor dem ersten vollständigen Eintrag abgeschnitten (Grenze der Ausgabe)"
_ENTRY = re.compile(r"\{[^{}]*\}")  # one entry of a list the limit cut off; nothing nests in it, so the scan is linear


@dataclass
class EntityLlmJob:
    """What the LLM ways need: the client, the budget of the request and its deadline."""

    client: BApiClient
    budget: RequestBudget
    deadline: Deadline | None = None


@dataclass
class EntitiesLlmReport(Usage):
    named: int = 0  # entities the model named whose word stands in the text
    checked: int = 0  # articles the model graded readably; 0 when it was not asked or gave no usable answer
    dropped: list[str] = field(default_factory=list)  # articles the check did not grade 2
    fallback: str | None = None  # the first reason the model's answer did not decide: why the rules decided
    reason: str | None = None  # the reason of the step that failed last, for its own note

    def count(self, answer: ChatResult | LlmSkipped, prompt_tag: str) -> None:
        """As ``Usage.count``, but naming and checking both keep their prompt."""
        tags = self.prompts
        super().count(answer, prompt_tag)
        if isinstance(answer, ChatResult):
            self.prompts = [*tags, prompt_tag]

    def fail(self, reason: str) -> None:
        """A step gave no usable answer; the first reason stays the report's, as naming and checking can both fail."""
        self.reason = reason
        if self.fallback is None:
            self.fallback = reason


class Link(NamedTuple):
    """One linked article as the check sees it: a word of the text, the title and the lead of the article."""

    mention: str
    title: str
    lead: str


def named_mentions(
    job: EntityLlmJob, text: str, report: EntitiesLlmReport, *, max_entities: int = 50
) -> list[Mention] | None:
    """The entities the model names in ``text``, each with the title it named; ``None`` without a usable answer.

    A word that stands nowhere in the text is left out: the entity would have no place to point to. An answer the
    limit of the output cut off keeps its complete entries.
    """
    prompt = get_prompt("entity_extraction")
    answer = budgeted_chat(
        job.client,
        prompt.render(text=text),
        max_output_tokens=max(EXTRACTION_OUTPUT_TOKENS, EXTRACTION_TOKENS_PER_ENTITY * max_entities),
        budget=job.budget,
        what="Entitäten",
        deadline=job.deadline,
    )
    report.count(answer, prompt.tag)
    if isinstance(answer, LlmSkipped):
        report.fail(answer.reason)
        return None
    pairs = _named_pairs(answer.text)
    if pairs is None:
        report.fail(CUT_OFF if answer.finish_reason == "length" else UNREADABLE)
        return None
    mentions = _placed(text, pairs)
    report.named = len(mentions)
    return mentions


def _named_pairs(answer: str) -> list[tuple[str, str]] | None:
    """The (word, title) pairs of an answer; ``None`` when it holds none that can be read.

    An empty list is an answer - the text names nothing -, a list of names without titles is not.
    """
    data = read_object(answer)
    items = data.get("entitaeten") if data is not None else None
    if isinstance(items, list) and not items:
        return []
    if not isinstance(items, list):
        items = [_loads(found.group()) for found in _ENTRY.finditer(answer)]
    pairs = [pair for pair in map(_pair, items) if pair is not None]
    return pairs or None


def _pair(item: object) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    word, title = item.get("text"), item.get("titel")
    if not isinstance(word, str) or not isinstance(title, str) or not word.strip() or not title.strip():
        return None
    return word.strip(), title.strip()


def _loads(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _placed(text: str, pairs: list[tuple[str, str]]) -> list[Mention]:
    """Each named word at its place, in the order of the answer. The longest words are placed first, so a shorter
    one looks past the places they took: "Optik" stands on its own, not inside "Geometrische Optik"."""
    lowered = _lower_aligned(text)
    taken: list[tuple[int, int]] = []
    placed: dict[int, Mention] = {}
    for index in sorted(range(len(pairs)), key=lambda i: -len(pairs[i][0])):
        word, title = pairs[index]
        place = _place(text, lowered, word, taken)
        if place is not None:
            start, end = place
            taken.append(place)
            placed[index] = Mention(text=text[start:end], start=start, end=end, kind="", source="llm", title=title)
    return [placed[index] for index in sorted(placed)]


def _lower_aligned(text: str) -> str:
    """The text in lower case, character for character, so a place in it is a place in the text; a character whose
    lower case is longer ("İ") stays as it is."""
    lowered = text.lower()
    if len(lowered) == len(text):  # lower case never drops a character, so equal length means one for one
        return lowered
    return "".join(low if len(low := char.lower()) == 1 else char for char in text)


def _place(text: str, lowered: str, word: str, taken: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Where ``word`` first stands in ``text`` as a whole word - as the model wrote it, else in another case - and
    only then inside a longer word ("schwefel" in "schwefelsäure"). A place a longer named word took counts only when
    there is no other; ``None`` when the word stands nowhere or is too long to be a name."""
    if len(word) > MAX_WORD_CHARS:
        return None
    first: tuple[int, int] | None = None
    for whole in (True, False):
        for start, end in _found(text, lowered, word):
            if whole and not _whole_word(text, start, end):
                continue
            if not any(start < until and since < end for since, until in taken):
                return start, end
            first = first or (start, end)
    return first


def _found(text: str, lowered: str, word: str) -> Iterator[tuple[int, int]]:
    """The places of ``word``, as written and then in any case. ``str.find`` scans in linear time - a regular
    expression would cost text length times word length, and the model repeats what the caller's text says."""
    yield from _occurrences(text, word)
    yield from _occurrences(lowered, _lower_aligned(word))


def _occurrences(haystack: str, needle: str) -> Iterator[tuple[int, int]]:
    start, tries = haystack.find(needle), 0
    while start >= 0 and tries < MAX_TRIES:
        yield start, start + len(needle)
        start, tries = haystack.find(needle, start + 1), tries + 1


def _whole_word(text: str, start: int, end: int) -> bool:
    return (start == 0 or not _word_char(text[start - 1])) and (end == len(text) or not _word_char(text[end]))


def _word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def grade_links(
    job: EntityLlmJob, text: str, links: Sequence[Link], report: EntitiesLlmReport
) -> list[int | None] | None:
    """The model's grade for each link, in the order of ``links``, in one call; ``None`` without a usable answer.

    A link the model left out, or graded with something other than 0, 1 or 2, has no grade (``None``); an answer
    without one readable grade is no answer - otherwise a model that numbered the links its own way would drop them
    all.
    """
    alias = {f"a{number}": link for number, link in enumerate(links, 1)}
    lines = "\n".join(
        f"{a}: „{link.mention}“ → {link.title}: {' '.join(link.lead.split())[:LEAD_CHARS]}" for a, link in alias.items()
    )
    prompt = get_prompt("entity_check")
    answer = budgeted_chat(
        job.client,
        prompt.render(text=text, lines=lines),
        max_output_tokens=CHECK_OUTPUT_TOKENS_PER_LINK * len(alias) + CHECK_OUTPUT_TOKENS,
        budget=job.budget,
        what="Prüfung der Entitäten",
        deadline=job.deadline,
    )
    report.count(answer, prompt.tag)
    if isinstance(answer, LlmSkipped):
        report.fail(answer.reason)
        return None
    data = read_object(answer.text)
    grades = [_grade(data.get(a)) for a in alias] if data is not None else []
    readable = sum(1 for grade in grades if grade is not None)
    if not readable:
        report.fail(UNREADABLE)
        return None
    report.checked = readable
    return grades


def _grade(value: object) -> int | None:
    number = read_number(value)
    return number if number in GRADES else None
