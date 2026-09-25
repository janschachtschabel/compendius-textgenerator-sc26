"""LLM article choice (article_choice=llm, D35): the model helps choose the articles of a compendium.

Two steps, both measured against the gold of eval/artikelwahl on 2026-09-23 (docs/entwicklung/02-weltwissen.md, M8):

- The main article, where the rules are unsure. The rules alone found 55 of 59, 22 of 23 and 9 of 12 main articles;
  with the model deciding their unsure resolutions it was 57, 23 and 11, at about 950 tokens for each of the 18 of
  94 requests it was asked for. The model sees the topic, the subject and the candidates the rules weighed, each
  with the beginning of its text, and answers with a number; when none fits it may name the title of a German
  Wikipedia article, which counts only when the archive has it.
- The side articles of the corpus. The model rates every article of the corpus on the scale of the gold, with the
  prompt of the M8 judge, and the full-text hits it rates 0 are dropped: 11 of the 16 hits the gold calls unfit, none
  that fit, and of the paragraphs the standard strategy printed from unfit articles 10 instead of 26 were left, at
  about 890 tokens for each of the 16 of 20 topics that had hits. Rated alone, without the rest of the corpus to
  compare, the model let most unfit hits through (6 of 16). Since M25 (2026-09-25, gpt-6-luna) the linked
  sub-articles rated 0 go as well: over the same 20 topics, after the hits without a link to the main article are
  gone (ZimRegistry.build_corpus), 5 instead of 12 printed paragraphs of unfit articles were left, the model rated
  no fitting or related article 0, and the call ran for 20 instead of 15 topics at about 750 tokens each.

Whatever keeps the model from answering usably - b-api, budget, time, an unreadable answer - leaves the rules'
article and every side article, and the reason goes to the audit.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import Source
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient, ChatResult
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt

OUTPUT_TOKENS = 60
NO_SUBJECT = "nicht angegeben"
UNREADABLE = "Antwort nicht lesbar"
INVALID_NUMBER = "Antwort ohne gültige Nummer"
NOTHING_FITS = "kein Kandidat passt, kein Titel genannt"
NAMED_TITLE_MISSING = "genannter Titel ist kein Artikel des Archivs"
CHECKED_ORIGINS = frozenset({"search", "linked"})  # the side articles the hit check may drop (M25)
HIT_OPENING_CHARS = 180  # as the M8 judge saw each article
HIT_OUTPUT_TOKENS_PER_ARTICLE = 12
HIT_SEED = 20260923  # the order of the articles in the call, fixed per topic as measured
_JSON = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ArticleChoiceJob:
    """What article_choice=llm needs: the client, the budget of the request and its deadline."""

    client: BApiClient
    budget: RequestBudget
    deadline: Deadline | None = None


@dataclass
class Usage:
    """The calls and tokens of one LLM step, and the model and prompt of the call that answered."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None
    prompts: list[str] = field(default_factory=list)

    def count(self, answer: ChatResult | LlmSkipped, prompt_tag: str) -> None:
        """Add the cost of a call; a call that answered also names its model and prompt."""
        self.calls += answer.calls if isinstance(answer, LlmSkipped) else 1
        self.prompt_tokens += answer.prompt_tokens
        self.completion_tokens += answer.completion_tokens
        self.total_tokens += answer.total_tokens
        if isinstance(answer, ChatResult):
            self.model = answer.model
            self.prompts = [prompt_tag]


@dataclass
class ArticleChoiceReport(Usage):
    offered: int = 0  # candidates shown to the model; 0 when the rules were sure and it was not asked
    named: str | None = None  # a title the model named instead of choosing a candidate
    fallback: str | None = None  # why the model's answer did not decide


@dataclass
class HitCheckReport(Usage):
    checked: int = 0  # side articles in the corpus; 0 when there were none and the model was not asked
    rated: int = 0  # articles in the call: the whole corpus, so the model can compare
    dropped: list[str] = field(default_factory=list)  # titles of the side articles rated 0
    fallback: str | None = None  # why every side article stayed although the model was asked

    @property
    def answered(self) -> bool:
        """The model rated the side articles: its answer decided which stay, also when all of them do."""
        return bool(self.prompts) and self.fallback is None


class LlmArticleChooser:
    """What the registry asks with the (title, opening) candidates of an unsure resolution.

    Answers ``(index, None)`` for a candidate, ``(None, title)`` for a title the model named, ``(None, None)`` when
    the rules' article stays; ``report`` says what happened and what it cost.
    """

    def __init__(self, job: ArticleChoiceJob, topic: str, subjects: Sequence[str]) -> None:
        self.job = job
        self.topic = topic
        self.subjects = list(subjects)  # names, all of equal weight (a node's subjects are a multi-valued field)
        self.prompt = get_prompt("article_choice")
        self.report = ArticleChoiceReport()

    def __call__(self, candidates: Sequence[tuple[str, str]]) -> tuple[int | None, str | None]:
        report = self.report
        report.offered = len(candidates)
        listing = "\n".join(f"{number}. {title}: {opening}" for number, (title, opening) in enumerate(candidates, 1))
        subject = ", ".join(self.subjects) or NO_SUBJECT
        messages = self.prompt.render(topic=self.topic, subject=subject, candidates=listing)
        answer = budgeted_chat(
            self.job.client,
            messages,
            max_output_tokens=OUTPUT_TOKENS,
            budget=self.job.budget,
            what="Artikelwahl",
            deadline=self.job.deadline,
        )
        report.count(answer, self.prompt.tag)
        if isinstance(answer, LlmSkipped):
            report.fallback = answer.reason
            return None, None
        data = read_object(answer.text)
        if data is None:
            report.fallback = UNREADABLE
            return None, None
        number = _number(data.get("wahl"))
        if number is not None and 1 <= number <= len(candidates):
            return number - 1, None
        named = str(data.get("titel") or "").strip()
        if named:
            report.named = named
            return None, named
        report.fallback = NOTHING_FITS if number == 0 else INVALID_NUMBER
        return None, None


def check_hits(job: ArticleChoiceJob, topic: str, sources: Sequence[Source]) -> tuple[set[str], HitCheckReport]:
    """The ids of the side articles the model rates as not fitting the topic, and what the check did and cost.

    The call holds every article of the corpus (``rate_articles``); only full-text hits and linked sub-articles can be
    dropped - the main article, its twin, the node's article and the materials stay. Without side articles the model
    is not asked.
    """
    report = HitCheckReport(checked=sum(1 for s in sources if s.origin in CHECKED_ORIGINS))
    if not report.checked:
        return set(), report
    notes = rate_articles(job, topic, sources, report)
    if notes is None:
        return set(), report
    gone = [s for s in sources if s.origin in CHECKED_ORIGINS and notes.get(s.source_id) == 0]
    report.dropped = [s.title for s in gone]
    return {s.source_id for s in gone}, report


def rate_articles(
    job: ArticleChoiceJob, topic: str, sources: Sequence[Source], report: HitCheckReport
) -> dict[str, int | None] | None:
    """The model's note for every article of the corpus by source id - 2 fits, 1 related, 0 does not - in one call.

    The articles go in an order fixed per topic, each with its title and the beginning of its text. ``None`` when
    the model gave no usable answer; ``report`` gets the cost and the reason.
    """
    by_key = {f"{s.project}:{s.title}": s for s in sources}
    keys = sorted(by_key)
    random.Random(f"{HIT_SEED}:{topic}").shuffle(keys)  # noqa: S311 - a reproducible order, not a secret
    alias = {f"a{number}": by_key[key] for number, key in enumerate(keys, 1)}
    report.rated = len(alias)
    listing = "\n".join(
        f"{a}: {s.title} — {' '.join(s.lead_text.split())[:HIT_OPENING_CHARS]}" for a, s in alias.items()
    )
    prompt = get_prompt("hit_check")
    answer = budgeted_chat(
        job.client,
        prompt.render(topic=topic, articles=listing),
        max_output_tokens=HIT_OUTPUT_TOKENS_PER_ARTICLE * len(alias),
        budget=job.budget,
        what="Trefferprüfung",
        deadline=job.deadline,
    )
    report.count(answer, prompt.tag)
    if isinstance(answer, LlmSkipped):
        report.fallback = answer.reason
        return None
    notes = read_object(answer.text)
    if notes is None:
        report.fallback = UNREADABLE
        return None
    return {s.source_id: _number(notes.get(a)) for a, s in alias.items()}


def choice_used(chose_article: bool, hit_check: HitCheckReport | None) -> str:
    """``llm`` when the model's answer decided anything, the article or which full-text hits stay; else the rules."""
    return "llm" if chose_article or (hit_check is not None and hit_check.answered) else "rule-based"


def choice_block(
    requested: str,
    used: str,
    needed: bool,
    choice: ArticleChoiceReport | None,
    chosen: str | None,
    hit_check: HitCheckReport | None,
) -> dict[str, Any]:
    """What article_choice asked and decided, for the audit of a compendium and the answer of /knowledge.

    ``used`` is ``llm`` when the model's answer decided anything, the article or the hits; ``needed`` says whether
    there was anything to ask, ``chosen`` is the article the model decided on.
    """
    fallback = choice.fallback if choice else None
    if choice is not None and choice.named and chosen is None:
        fallback = NAMED_TITLE_MISSING
    return {
        "requested": requested,
        "used": used,
        "needed": needed,
        "asked": bool(choice and choice.offered),  # false when the rules were sure or the LLM is not usable
        "offered": choice.offered if choice else 0,
        "chosen": chosen,
        "named": choice.named if choice else None,
        "fallback": fallback,
        "hits_checked": hit_check.checked if hit_check else 0,
        "hits_dropped": list(hit_check.dropped) if hit_check else [],
        "hits_fallback": hit_check.fallback if hit_check else None,
    }


def read_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in a model's answer, or ``None`` when there is none."""
    match = _JSON.search(text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _number(value: Any) -> int | None:
    if isinstance(value, bool):  # JSON true is no number, though Python counts it as 1
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None
