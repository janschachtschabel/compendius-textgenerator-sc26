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

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from app.knowledge.article_choice import Usage, read_number, read_object
from app.knowledge.recognise import Mention
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient, ChatResult
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt

EXTRACTION_OUTPUT_TOKENS = 1200  # as measured; a text of a material named about eight entities
CHECK_OUTPUT_TOKENS_PER_LINK = 20
CHECK_OUTPUT_TOKENS = 200
LEAD_CHARS = 180  # what the check sees of an article, as the hit check of the article choice
UNREADABLE = "Antwort nicht lesbar"


@dataclass
class EntityLlmJob:
    """What the LLM ways need: the client, the budget of the request and its deadline."""

    client: BApiClient
    budget: RequestBudget
    deadline: Deadline | None = None


@dataclass
class EntitiesLlmReport(Usage):
    named: int = 0  # entities the model named whose word stands in the text
    checked: int = 0  # articles the model graded; 0 when it was not asked or gave no usable answer
    dropped: list[str] = field(default_factory=list)  # articles the check did not grade 2
    fallback: str | None = None  # why the model's answer did not decide although it was asked

    def count(self, answer: ChatResult | LlmSkipped, prompt_tag: str) -> None:
        """As ``Usage.count``, but naming and checking both keep their prompt."""
        tags = self.prompts
        super().count(answer, prompt_tag)
        if isinstance(answer, ChatResult):
            self.prompts = [*tags, prompt_tag]


class Link(NamedTuple):
    """One linked article as the check sees it: a word of the text, the title and the lead of the article."""

    mention: str
    title: str
    lead: str


def named_mentions(job: EntityLlmJob, text: str, report: EntitiesLlmReport) -> list[Mention] | None:
    """The entities the model names in ``text``, each with the title it named; ``None`` without a usable answer.

    A word that stands nowhere in the text is left out: the entity would have no place to point to.
    """
    prompt = get_prompt("entity_extraction")
    answer = budgeted_chat(
        job.client,
        prompt.render(text=text),
        max_output_tokens=EXTRACTION_OUTPUT_TOKENS,
        budget=job.budget,
        what="Entitäten",
        deadline=job.deadline,
    )
    report.count(answer, prompt.tag)
    if isinstance(answer, LlmSkipped):
        report.fallback = answer.reason
        return None
    data = read_object(answer.text)
    items = data.get("entitaeten") if data is not None else None
    if not isinstance(items, list):
        report.fallback = UNREADABLE
        return None
    mentions: list[Mention] = []
    for item in items:
        word = str(item.get("text") or "").strip() if isinstance(item, dict) else ""
        title = str(item.get("titel") or "").strip() if isinstance(item, dict) else ""
        place = _place(text, word) if word and title else None
        if place is not None:
            start, end = place
            mentions.append(Mention(text=text[start:end], start=start, end=end, kind="", source="llm", title=title))
    report.named = len(mentions)
    return mentions


def _place(text: str, word: str) -> tuple[int, int] | None:
    """Where ``word`` first stands in ``text`` as a whole word - as the model wrote it, else in another case - and
    only then where it first stands inside a longer word ("schwefel" in "schwefelsäure", M36 in the service)."""
    escaped = re.escape(word)  # an escaped word: linear, whatever the model wrote
    for pattern in (rf"(?<!\w){escaped}(?!\w)", escaped):
        found = re.search(pattern, text) or re.search(pattern, text, re.IGNORECASE)
        if found is not None:
            return found.start(), found.end()
    return None


def grade_links(
    job: EntityLlmJob, text: str, links: Sequence[Link], report: EntitiesLlmReport
) -> list[int | None] | None:
    """The model's grade for each link, in the order of ``links``, in one call; ``None`` without a usable answer.

    A link the model left out has no grade (``None``).
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
        report.fallback = answer.reason
        return None
    grades = read_object(answer.text)
    if grades is None:
        report.fallback = UNREADABLE
        return None
    report.checked = len(alias)
    return [read_number(grades.get(a)) for a in alias]
