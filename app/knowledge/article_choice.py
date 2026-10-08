"""LLM article choice (article_choice=llm, D35): the model helps choose the articles of a compendium.

Two steps, both measured against the gold of eval/artikelwahl on 2026-09-23 (docs/entwicklung/02-weltwissen.md, M8):

- The main article, where the rules are unsure. The rules alone found 55 of 59, 22 of 23 and 9 of 12 main articles;
  with the model deciding their unsure resolutions it was 57, 23 and 11, at about 950 tokens for each of the 18 of
  94 requests it was asked for. The model sees the topic, the subject and the candidates the rules weighed, each
  with the beginning of its text, and answers with a number; when none fits it may name the title of a German
  Wikipedia article, which counts only when the archive has it. Naming no candidate and no title is its verdict that
  none fits (A01, audit 2026-10-02): the rules' article goes as well, and the overview of question N or nothing takes
  its place (ZimRegistry.resolve_topic). Over 215 topics (M63) that was 4 to 5 bare words with several meanings and
  no subject, where the rules had kept a random meaning ("Stamm (Familienname)", "Funktion (Objekt)").
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

Since D63 the model first names the overview and the parts of a topic (app/knowledge/topic_articles.py, M37): the
articles of the archive among them replace the linked sub-articles and the full-text hits, so the hit check has
nothing left to rate, and the overview replaces the rules' article where they missed the topic.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.domain.models import Source
from app.knowledge.resolution import NONE_FITS
from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt
from app.llm.usage import Usage

if TYPE_CHECKING:  # node_article and topic_articles build on this module
    from app.knowledge.node_article import NodeArticleReport
    from app.knowledge.topic_articles import TopicArticlesReport

OUTPUT_TOKENS = 60
NO_SUBJECT = "nicht angegeben"
UNREADABLE = "Antwort nicht lesbar"
INVALID_NUMBER = "Antwort ohne gültige Nummer"
NO_NOTES = "Antwort ohne Note für einen Artikel"  # an object, but none of its keys names a listed article
NAMED_TITLE_MISSING = "genannter Titel ist kein Artikel des Archivs"
CHECKED_ORIGINS = frozenset({"search", "linked"})  # the side articles the hit check may drop (M25)
HIT_OPENING_CHARS = 180  # as the M8 judge saw each article
HIT_OUTPUT_TOKENS_PER_ARTICLE = 12
HIT_SEED = 20260923  # the order of the articles in the call, fixed per topic as measured
# A number in an answer: "²" and "①" are digits to str.isdigit, and int() refuses them (audit 2026-09-27,
# KO-03)
_NUMBER = re.compile("[0-9]{1,3}")


@dataclass
class ArticleChoiceJob:
    """What article_choice=llm needs: the client, the budget of the request and its deadline; ``thorough`` is
    article_choice=llm-thorough, which also shows the model a sure resolution of a word with several meanings (D61)."""

    client: BApiClient
    budget: RequestBudget
    deadline: Deadline | None = None
    thorough: bool = False


@dataclass
class ArticleChoiceReport(Usage):
    offered: int = 0  # candidates shown to the model; 0 when the rules were sure and it was not asked
    named: str | None = None  # a title the model named instead of choosing a candidate
    rejected: bool = False  # the model found that no candidate fits: the rules' article went as well (D85, A01)
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

    Answers ``(index, None)`` for a candidate, ``(None, title)`` for a title the model named, ``(NONE_FITS, None)``
    when it finds that no candidate fits (A01), and ``(None, None)`` when the rules' article stays because the
    answer was of no use; ``report`` says what happened and what it cost.
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
            prompt=self.prompt.id,
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
        number = read_number(data.get("wahl"))
        if number is not None and 1 <= number <= len(candidates):
            return number - 1, None
        named = str(data.get("titel") or "").strip()
        report.rejected = number == 0  # the verdict that no candidate fits, a title named or not (D85)
        if named:
            report.named = named
            return None, named
        if number == 0:
            return NONE_FITS, None
        report.fallback = INVALID_NUMBER
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
        prompt=prompt.id,
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
    rated = {s.source_id: read_number(notes.get(a)) for a, s in alias.items()}
    if not any(note in (0, 1, 2) for note in rated.values()):
        # nothing decided: it kept every hit, as the rules do, and must not count as the model's choice (2026-10-08)
        report.fallback = NO_NOTES
        return None
    return rated


def choice_used(
    chose_article: bool, hit_check: HitCheckReport | None, articles: TopicArticlesReport | None = None
) -> str:
    """``llm`` when the model's answer decided anything - the article, the articles of the topic (D63) or which side
    articles stay; else the rules."""
    named = articles is not None and (articles.main or articles.parts > 0)
    return "llm" if chose_article or named or (hit_check is not None and hit_check.answered) else "rule-based"


@dataclass(frozen=True)
class ChoiceAudit:
    """What the article choice of a request asked and decided (D35, D47, D61, D63), for the LLM report of a
    compendium and the answers of /knowledge and the curriculum search.

    ``requested`` and ``used`` read as the switch does, ``llm`` or ``rule-based``: ``used`` is ``llm`` when the model's
    answer decided anything, the article or the side articles. ``needed`` says whether there was anything to ask (an
    unsure article, side articles, a material or the articles of a topic), ``chosen`` is the article the model decided
    on, ``hit_check`` its check of the side articles, ``node`` its question about a material and ``articles`` what it
    named for the topic. It was a dict spread into the parameters of the report (audit 2026-09-28, WA-06).
    """

    requested: str = "rule-based"
    used: str = "rule-based"
    report: ArticleChoiceReport | None = None
    chosen: str | None = None
    needed: bool = False
    hit_check: HitCheckReport | None = None
    node: NodeArticleReport | None = None
    articles: TopicArticlesReport | None = None


def choice_block(audit: ChoiceAudit) -> dict[str, Any]:
    """What article_choice asked and decided, for the audit of a compendium and the answer of /knowledge."""
    choice, chosen, hit_check, articles = audit.report, audit.chosen, audit.hit_check, audit.articles
    fallback = choice.fallback if choice else None
    if choice is not None and choice.named and chosen is None:
        fallback = NAMED_TITLE_MISSING
    return {
        "requested": audit.requested,
        "used": audit.used,
        "needed": audit.needed,
        "asked": bool(choice and choice.offered),  # false when the rules were sure or the LLM is not usable
        "offered": choice.offered if choice else 0,
        "chosen": chosen,
        "named": choice.named if choice else None,
        "rejected": bool(choice and choice.rejected),  # no candidate fitted: the rules' article went (A01)
        "fallback": fallback,
        "hits_checked": hit_check.checked if hit_check else 0,
        "hits_dropped": list(hit_check.dropped) if hit_check else [],
        "hits_fallback": hit_check.fallback if hit_check else None,
        "articles_asked": bool(articles and articles.calls),  # false for a material, or when budget or time were short
        "articles_found": list(articles.found) if articles else [],  # the overview (when found) first
        "articles_overview": articles.overview_title if articles else None,  # None: a part stood in for it
        "articles_main": bool(articles and articles.main),  # the overview replaced the rules' article
        "articles_covers": articles.covers if articles else None,  # the overview covers the topic as asked (V3)
        "articles_fallback": articles.fallback if articles else None,
    }


def read_object(text: str) -> dict[str, Any] | None:
    """The JSON object in a model's answer, from its first opening brace to its last closing one, or ``None`` when
    there is none. Found by position: the pattern of before, tried from every brace of a run, took 0.23 s for 20,000
    braces without a closing one (review of 2026-10-08)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except (ValueError, RecursionError):  # also a number of over 4,300 digits and a nesting too deep to read
        return None
    return data if isinstance(data, dict) else None


def read_number(value: Any) -> int | None:
    """A whole number from a model's JSON value - an int or up to three ASCII digits - or ``None``."""
    if isinstance(value, bool):  # JSON true is no number, though Python counts it as 1
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _NUMBER.fullmatch(value.strip()):
        return int(value.strip())  # str.strip takes U+001C to U+001F for blanks, int() does not (KO-25)
    return None
