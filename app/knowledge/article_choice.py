"""LLM article choice (article_choice=llm, D35): the model decides the article where the rules are unsure.

Measured against the three gold files of eval/artikelwahl on 2026-09-23 (docs/entwicklung/02-weltwissen.md, M8): the
rules alone found 55 of 59, 22 of 23 and 9 of 12 main articles; with the model deciding their unsure resolutions it
was 57, 23 and 11, at about 950 tokens for each of the 18 of 94 requests it was asked for. The model sees the topic,
the subject and the candidates the rules weighed, each with the beginning of its text, and answers with a number;
when none fits it may name the title of a German Wikipedia article, which counts only when the archive has it.

Whatever keeps the model from answering usably - b-api, budget, time, an unreadable answer - leaves the rules'
article, and the reason goes to the audit.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.llm.budget import RequestBudget
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.client import BApiClient
from app.llm.deadline import Deadline
from app.llm.prompts import get_prompt

OUTPUT_TOKENS = 60
NO_SUBJECT = "nicht angegeben"
UNREADABLE = "Antwort nicht lesbar"
INVALID_NUMBER = "Antwort ohne gültige Nummer"
NOTHING_FITS = "kein Kandidat passt, kein Titel genannt"
_JSON = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ArticleChoiceJob:
    """What article_choice=llm needs: the client, the budget of the request and its deadline."""

    client: BApiClient
    budget: RequestBudget
    deadline: Deadline | None = None


@dataclass
class ArticleChoiceReport:
    offered: int = 0  # candidates shown to the model; 0 when the rules were sure and it was not asked
    named: str | None = None  # a title the model named instead of choosing a candidate
    fallback: str | None = None  # why the model's answer did not decide
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None
    prompts: list[str] = field(default_factory=list)


class LlmArticleChooser:
    """What the registry asks with the (title, opening) candidates of an unsure resolution.

    Answers ``(index, None)`` for a candidate, ``(None, title)`` for a title the model named, ``(None, None)`` when
    the rules' article stays; ``report`` says what happened and what it cost.
    """

    def __init__(self, job: ArticleChoiceJob, topic: str, subject: str | None) -> None:
        self.job = job
        self.topic = topic
        self.subject = subject
        self.prompt = get_prompt("article_choice")
        self.report = ArticleChoiceReport()

    def __call__(self, candidates: Sequence[tuple[str, str]]) -> tuple[int | None, str | None]:
        report = self.report
        report.offered = len(candidates)
        listing = "\n".join(f"{number}. {title}: {opening}" for number, (title, opening) in enumerate(candidates, 1))
        messages = self.prompt.render(topic=self.topic, subject=self.subject or NO_SUBJECT, candidates=listing)
        answer = budgeted_chat(
            self.job.client,
            messages,
            max_output_tokens=OUTPUT_TOKENS,
            budget=self.job.budget,
            what="Artikelwahl",
            deadline=self.job.deadline,
        )
        if isinstance(answer, LlmSkipped):
            report.calls += answer.calls
            report.prompt_tokens += answer.prompt_tokens
            report.completion_tokens += answer.completion_tokens
            report.total_tokens += answer.total_tokens
            report.fallback = answer.reason
            return None, None
        report.calls += 1
        report.prompt_tokens += answer.prompt_tokens
        report.completion_tokens += answer.completion_tokens
        report.total_tokens += answer.total_tokens
        report.model = answer.model
        report.prompts = [self.prompt.tag]
        data = _read_object(answer.text)
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


def _read_object(text: str) -> dict[str, Any] | None:
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
