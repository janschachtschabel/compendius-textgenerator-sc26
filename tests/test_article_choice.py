"""article_choice=llm (D35): the LLM decides the article when the rules are unsure (M8, docs/entwicklung)."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import ArticleChoiceJob, LlmArticleChooser
from app.llm.prompts import get_prompt
from app.service import CompendiumService
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

CHOICE_PROMPT = get_prompt("article_choice").tag
CANDIDATES = [("Optik", "Die Optik ist ein Gebiet der Physik."), ("Optik (Album)", "Optik ist ein Album.")]


def answering(answer: Any) -> Callable[[dict[str, Any]], str]:
    return lambda body: answer if isinstance(answer, str) else json.dumps(answer)


def chooser_for(fake: FakeBApi, subject: str | None = "Physik") -> LlmArticleChooser:
    gateway = make_gateway(fake, per_request=100_000)
    return LlmArticleChooser(ArticleChoiceJob(gateway.client, gateway.open_budget()), topic="Optik", subject=subject)


def test_the_model_picks_a_candidate_by_its_number() -> None:
    fake = FakeBApi(answering({"wahl": 2, "titel": ""}))
    chooser = chooser_for(fake)
    assert chooser(CANDIDATES) == (1, None)

    user = fake.bodies[0]["messages"][1]["content"]
    assert "Thema: Optik" in user and "Schulfach: Physik" in user
    assert "1. Optik: Die Optik ist ein Gebiet der Physik.\n2. Optik (Album): Optik ist ein Album." in user
    report = chooser.report
    assert report.offered == 2 and report.calls == 1 and report.total_tokens == 24 and report.fallback is None
    assert report.prompts == [CHOICE_PROMPT] and report.model == "gpt-5.6-luna"


def test_without_a_subject_the_prompt_says_so() -> None:
    fake = FakeBApi(answering({"wahl": 1}))
    chooser_for(fake, subject=None)(CANDIDATES)
    assert "Schulfach: nicht angegeben" in fake.bodies[0]["messages"][1]["content"]


def test_the_model_may_name_a_title_instead() -> None:
    chooser = chooser_for(FakeBApi(answering({"wahl": 0, "titel": "Geometrische Optik"})))
    assert chooser(CANDIDATES) == (None, "Geometrische Optik")
    assert chooser.report.fallback is None


@pytest.mark.parametrize("answer", ["keine Ahnung", {"wahl": 5}, {"wahl": 0, "titel": ""}, {"wahl": True}])
def test_an_answer_that_names_nothing_leaves_the_rules_decision(answer: Any) -> None:
    chooser = chooser_for(FakeBApi(answering(answer)))
    assert chooser(CANDIDATES) == (None, None)
    assert chooser.report.fallback and chooser.report.calls == 1


def test_a_failed_call_leaves_the_rules_decision() -> None:
    chooser = chooser_for(FakeBApi(statuses=[500]))
    assert chooser(CANDIDATES) == (None, None)
    assert chooser.report.fallback is not None and chooser.report.fallback.startswith("b-api")


def test_an_unsure_resolution_is_decided_by_the_chooser(service: CompendiumService) -> None:
    offered: list[list[str]] = []

    def pick_technical(candidates: Sequence[tuple[str, str]]) -> tuple[int | None, str | None]:
        titles = [title for title, _ in candidates]
        offered.append(titles)
        return titles.index("Technische Optik"), None

    resolution = service.registry.resolve_topic("Geometrische", chooser=pick_technical)
    assert resolution.title == "Technische Optik" and resolution.method == "llm" and not resolution.confident
    assert offered == [["Geometrische Optik", "Optik", "Technische Optik", "Brechung (Physik)"]]
    assert resolution.alternatives[0] == "Geometrische Optik"  # the rules' article stays visible


def test_a_title_the_chooser_names_counts_when_the_archive_has_it(service: CompendiumService) -> None:
    named = service.registry.resolve_topic("Geometrische", chooser=lambda candidates: (None, "Lichtlehre"))
    assert named.title == "Optik" and named.method == "llm"  # the redirect is followed
    unknown = service.registry.resolve_topic("Geometrische", chooser=lambda candidates: (None, "Gibt es nicht"))
    assert unknown.title == "Geometrische Optik" and unknown.method == "suggestion"


def test_a_sure_resolution_never_asks_the_chooser(service: CompendiumService) -> None:
    def refuse(candidates: Sequence[tuple[str, str]]) -> tuple[int | None, str | None]:
        raise AssertionError("a sure resolution asked the chooser")

    assert service.registry.resolve_topic("Optik", chooser=refuse).method == "title"


def test_article_choice_llm_lets_the_model_decide_an_unsure_topic(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(answering({"wahl": 3, "titel": ""}))  # 3 = Technische Optik, see the test above
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Geometrische", article_choice="llm", parts=["world"]))

    assert result.resolution.title == "Technische Optik" and result.resolution.method == "llm"
    assert result.frontmatter["topic_resolution"]["method"] == "llm"
    assert next(s for s in result.sources if s.is_primary).title == "Technische Optik"
    assert result.audit.llm is not None and result.audit.llm["note"] is None
    choice = result.audit.llm["article_choice"]
    assert choice["requested"] == choice["used"] == "llm" and choice["chosen"] == "Technische Optik"
    assert choice["offered"] == 4 and choice["needed"] and choice["asked"] and choice["fallback"] is None
    assert CHOICE_PROMPT in result.frontmatter["llm"]["prompts"]
    assert result.audit.llm_tokens == {"prompt": 20, "completion": 4, "total": 24, "calls": 1}


def test_a_sure_topic_costs_no_call(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBApi(answering({"wahl": 1}))
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(GenerateRequest(topic="Optik", article_choice="llm", parts=["world"]))

    assert fake.bodies == [] and result.resolution.method == "title"
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["requested"] == "llm" and choice["used"] == "rule-based"
    assert not choice["needed"] and not choice["asked"]


def test_article_choice_llm_without_a_usable_llm_keeps_the_rules_choice(service: CompendiumService) -> None:
    assert service.llm is None  # the test settings keep the b-api off
    result = service.generate(GenerateRequest(topic="Geometrische", article_choice="llm", parts=["world"]))

    assert result.resolution.title == "Geometrische Optik" and result.resolution.method == "suggestion"
    assert result.audit.llm is not None and "nicht konfiguriert" in result.audit.llm["note"]
    assert result.audit.llm["article_choice"]["used"] == "rule-based"


def test_the_rule_based_default_adds_no_llm_block(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Geometrische", parts=["world"]))
    assert result.audit.llm is None and result.resolution.method == "suggestion"
