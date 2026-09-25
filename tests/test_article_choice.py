"""article_choice=llm (D35): the LLM decides the article when the rules are unsure (M8, docs/entwicklung)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest

from app.domain.models import ArticleSection, Paragraph, Source
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import (
    NAMED_TITLE_MISSING,
    UNREADABLE,
    ArticleChoiceJob,
    ArticleChoiceReport,
    HitCheckReport,
    LlmArticleChooser,
    check_hits,
    choice_block,
    rate_articles,
)
from app.llm.prompts import get_prompt
from app.service import CompendiumService, LlmNotConfiguredError
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway
from tests.test_wlo_client import BASE, MATERIAL, FakeRepository

CHOICE_PROMPT = get_prompt("article_choice").tag
HIT_PROMPT = get_prompt("hit_check").tag
CANDIDATES = [("Optik", "Die Optik ist ein Gebiet der Physik."), ("Optik (Album)", "Optik ist ein Album.")]
LISTED = re.compile(r"^(a\d+): (.+?) — ", re.M)


def answering(answer: Any) -> Callable[[dict[str, Any]], str]:
    return lambda body: answer if isinstance(answer, str) else json.dumps(answer)


def rating(notes: dict[str, int]) -> Callable[[dict[str, Any]], str]:
    """Answers the hit check with a note per listed article, 2 unless ``notes`` names its title."""
    return lambda body: json.dumps(
        {alias: notes.get(title, 2) for alias, title in LISTED.findall(body["messages"][1]["content"])}
    )


def by_prompt(choice: Any, notes: dict[str, int] | None = None) -> Callable[[dict[str, Any]], str]:
    """One fake b-api for both calls of article_choice=llm: the choice of the article and the hit check."""
    hits = rating(notes or {})
    system = get_prompt("hit_check").system
    return lambda body: hits(body) if body["messages"][0]["content"] == system else json.dumps(choice)


def source(title: str, origin: str, lead: str = "Ein Artikel.") -> Source:
    return Source(
        source_id=f"wikipedia:{title}",
        project="wikipedia",
        title=title,
        url=f"https://de.wikipedia.org/wiki/{title}",
        origin=origin,
        sections=[ArticleSection(paragraphs=[Paragraph(text=lead)])],
    )


def chooser_for(fake: FakeBApi, subjects: Sequence[str] = ("Physik",)) -> LlmArticleChooser:
    gateway = make_gateway(fake, per_request=100_000)
    job = ArticleChoiceJob(gateway.client, gateway.open_budget())
    return LlmArticleChooser(job, topic="Optik", subjects=subjects)


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
    chooser_for(fake, subjects=())(CANDIDATES)
    assert "Schulfach: nicht angegeben" in fake.bodies[0]["messages"][1]["content"]


def test_several_subjects_are_named_alike() -> None:
    """A node's subjects weigh the same; the prompt names all of them in the line of the subject."""
    fake = FakeBApi(answering({"wahl": 1}))
    chooser_for(fake, subjects=("Biologie", "Physik"))(CANDIDATES)
    assert "Schulfach: Biologie, Physik" in fake.bodies[0]["messages"][1]["content"]


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


def test_the_hit_check_drops_side_articles_rated_zero_and_nothing_else() -> None:
    """Full-text hits and linked sub-articles rated 0 go; the main article, its twin and the node's article stay.

    Linked sub-articles used to stay whatever the model said. M25 measured on the term gold that dropping those
    rated 0 too leaves 11 instead of 17 printed paragraphs of unfit articles, and the model rated no fitting one 0.
    """
    corpus = [
        source("Optik", "primary"),
        source("Optik (Kinderlexikon)", "same_topic"),
        source("Brechung (Physik)", "linked"),
        source("Linse (Optik)", "node"),
        source("Lichtmikroskop", "search"),
        source("Kernwaffe", "search", "Eine Kernwaffe ist eine Waffe."),
    ]
    zero = dict.fromkeys(("Optik", "Optik (Kinderlexikon)", "Brechung (Physik)", "Linse (Optik)", "Kernwaffe"), 0)
    fake = FakeBApi(rating(zero))
    gateway = make_gateway(fake, per_request=100_000)
    gone, report = check_hits(ArticleChoiceJob(gateway.client, gateway.open_budget()), "Optik", corpus)

    assert gone == {"wikipedia:Brechung (Physik)", "wikipedia:Kernwaffe"}
    user = fake.bodies[0]["messages"][1]["content"]
    assert user.startswith("Thema des Kompendiums: Optik\n\nArtikel:\n")
    assert all(s.title in user for s in corpus)  # the whole corpus, so the model can compare
    assert ": Kernwaffe — Eine Kernwaffe ist eine Waffe." in user
    assert report.checked == 3 and report.rated == 6 and report.fallback is None
    assert report.dropped == ["Brechung (Physik)", "Kernwaffe"]
    assert report.calls == 1 and report.prompts == [HIT_PROMPT] and report.answered


def test_the_model_rates_every_article_of_the_corpus_in_one_call() -> None:
    corpus = [source("Optik", "primary"), source("Brechung (Physik)", "linked"), source("Kernwaffe", "search")]
    fake = FakeBApi(rating({"Kernwaffe": 0, "Brechung (Physik)": 1}))
    gateway = make_gateway(fake, per_request=100_000)
    report = HitCheckReport()
    notes = rate_articles(ArticleChoiceJob(gateway.client, gateway.open_budget()), "Optik", corpus, report)
    assert notes == {"wikipedia:Optik": 2, "wikipedia:Brechung (Physik)": 1, "wikipedia:Kernwaffe": 0}
    assert report.rated == 3 and report.calls == 1 and report.fallback is None


def test_without_side_articles_nothing_is_asked() -> None:
    fake = FakeBApi(rating({}))
    gateway = make_gateway(fake)
    corpus = [source("Optik", "primary"), source("Optik (Kinderlexikon)", "same_topic"), source("Linse", "node")]
    gone, report = check_hits(ArticleChoiceJob(gateway.client, gateway.open_budget()), "Optik", corpus)
    assert gone == set() and fake.bodies == [] and report.calls == 0 and not report.answered


def test_a_linked_sub_article_alone_is_reason_to_ask() -> None:
    fake = FakeBApi(rating({"Brechung (Physik)": 0}))
    gateway = make_gateway(fake, per_request=100_000)
    corpus = [source("Optik", "primary"), source("Brechung (Physik)", "linked")]
    gone, report = check_hits(ArticleChoiceJob(gateway.client, gateway.open_budget()), "Optik", corpus)
    assert gone == {"wikipedia:Brechung (Physik)"} and report.checked == 1 and report.calls == 1


def test_an_unreadable_hit_check_keeps_every_hit() -> None:
    gateway = make_gateway(FakeBApi(answering("keine Ahnung")))
    corpus = [source("Optik", "primary"), source("Kernwaffe", "search")]
    gone, report = check_hits(ArticleChoiceJob(gateway.client, gateway.open_budget()), "Optik", corpus)
    assert gone == set() and report.fallback == UNREADABLE and report.calls == 1 and not report.answered


def test_a_named_title_the_archive_lacks_is_the_reason_even_when_the_hit_check_answered() -> None:
    # The hit check answering makes the switch "used"; that must not hide why the article stayed the rules' one
    choice = ArticleChoiceReport(offered=2, named="Gibt es nicht", calls=1)
    hits = HitCheckReport(checked=1, rated=3, calls=1, prompts=[HIT_PROMPT])
    block = choice_block("llm", "llm", True, choice, None, hits)
    assert block["fallback"] == NAMED_TITLE_MISSING and block["chosen"] is None and block["hits_fallback"] is None


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
    fake = FakeBApi(by_prompt({"wahl": 3, "titel": ""}))  # 3 = Technische Optik, see the test above
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
    tokens = result.audit.llm_tokens
    assert tokens is not None and tokens["calls"] == len(fake.bodies) and tokens["total"] == 24 * tokens["calls"]


def test_article_choice_llm_drops_the_full_text_hits_the_model_rates_zero(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(by_prompt({"wahl": 1}, {"Augenoptiker": 0}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik", article_choice="llm", parts=["world"]))

    titles = [s.title for s in result.sources]
    assert "Augenoptiker" not in titles and "Lichtmikroskop" in titles  # the other hit stays
    assert len(fake.bodies) == 1  # "Optik" is sure: the only call is the hit check
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["used"] == "llm" and choice["needed"] and not choice["asked"]
    # checked: the side articles the model could drop - four linked sub-articles and the two full-text hits (M25)
    assert (
        choice["hits_checked"] == 6 and choice["hits_dropped"] == ["Augenoptiker"] and choice["hits_fallback"] is None
    )
    assert HIT_PROMPT in result.frontmatter["llm"]["prompts"]
    assert result.frontmatter["llm"]["article_choice"]["hits_dropped"] == ["Augenoptiker"]


def test_article_choice_llm_drops_a_linked_sub_article_the_model_rates_zero(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(by_prompt({"wahl": 1}, {"Technische Optik": 0}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Geometrische Optik", article_choice="llm", parts=["world"]))

    assert [s.title for s in result.sources] == ["Geometrische Optik"], "its only linked sub-article was rated 0"
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["used"] == "llm" and choice["hits_checked"] == 1 and choice["hits_dropped"] == ["Technische Optik"]


def test_a_sure_topic_without_side_articles_costs_no_call(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(answering({"wahl": 1}))
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(GenerateRequest(topic="Programmiersprache", article_choice="llm", parts=["world"]))

    assert [s.title for s in result.sources] == ["Programmiersprache"]
    assert fake.bodies == [] and result.resolution.method == "title"
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["requested"] == "llm" and choice["used"] == "rule-based"
    assert not choice["needed"] and not choice["asked"]


def test_article_choice_llm_without_a_configured_llm_is_refused(service: CompendiumService) -> None:
    assert service.llm is None  # the test settings keep the b-api off
    with pytest.raises(LlmNotConfiguredError, match="article_choice=llm"):
        service.generate(GenerateRequest(topic="Geometrische", article_choice="llm", parts=["world"]))


def test_an_llm_that_is_not_available_for_now_leaves_the_rules_choice(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(by_prompt({"wahl": 3, "titel": ""}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    monkeypatch.setattr(
        service, "llm_unavailable", lambda: "LLM nicht verfügbar (b-api antwortet nicht); Regelmodus verwendet"
    )
    result = service.generate(GenerateRequest(topic="Geometrische", article_choice="llm", parts=["world"]))

    assert result.resolution.title == "Geometrische Optik" and result.resolution.method == "suggestion"
    assert result.audit.llm is not None and "nicht verfügbar" in result.audit.llm["note"]
    assert result.audit.llm["article_choice"]["used"] == "rule-based" and fake.bodies == []


def test_the_rule_based_default_adds_no_llm_block(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Geometrische", parts=["world"]))
    assert result.audit.llm is None and result.resolution.method == "suggestion"


def test_with_a_configured_llm_the_default_profile_asks_it_and_the_rules_can_still_be_chosen(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service.settings, "preset_default", "balanced")  # the shipped profile (D53)
    fake = FakeBApi(by_prompt({"wahl": 3, "titel": ""}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    chosen = service.generate(GenerateRequest(topic="Geometrische", parts=["world"]))
    assert chosen.resolution.method == "llm" and chosen.audit.llm is not None
    assert chosen.audit.llm["article_choice"]["requested"] == "llm"

    calls = len(fake.bodies)
    ruled = service.generate(GenerateRequest(topic="Geometrische", article_choice="rule-based", parts=["world"]))
    assert ruled.resolution.method == "suggestion" and len(fake.bodies) == calls


def test_the_model_hears_every_subject_of_a_node_by_name(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The staging material names Biologie and Physik: both reach the prompt, by name - not the URI, not one alone."""
    fake = FakeBApi(by_prompt({"wahl": 1, "titel": ""}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    repository = EduSharingClient(BASE, transport=httpx.MockTransport(FakeRepository()))
    monkeypatch.setattr(service, "collections", CollectionBuilder(client=repository, cache=None))
    service.generate(GenerateRequest(topic="Geometrische", node_id=MATERIAL, article_choice="llm", parts=["world"]))
    by_system = {body["messages"][0]["content"]: body["messages"][1]["content"] for body in fake.bodies}
    # topic and material go to one question first (D47); it names no title here, so the rules and the choice decide
    assert "Fächer: Biologie, Physik\n" in by_system[get_prompt("node_topic_with_topic").system]
    assert "Schulfach: Biologie, Physik" in by_system[get_prompt("article_choice").system]
