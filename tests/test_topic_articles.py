"""The question N (D63): from balanced up the LLM names the overview and the parts of a topic (M37, M38, M39).

A compendium builds on one main article, its twin and the side articles its links and the full-text search bring. For
a topic that is a group or joins two subjects ("deutsche Dichter", "Klimawandel und Landwirtschaft") no single article
carries it. In M37 the question N - the model names the overview article and up to eight articles on the members,
parts or aspects of the topic - printed 87 instead of 45 % of the paragraphs from fitting articles, on ordinary topics
93 instead of 73 %, at about 500 tokens. Jan chose option C of the decision paper (point 9): N in balanced and the
best-quality profiles, llm-free stays without an LLM. The overview replaces the main article only where the rules miss
the topic - a title suggestion, a full-text hit, a list page -, and the articles N names replace the linked
sub-articles and the full-text hits. Without a usable answer the corpus is the one of before, hit check included.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from libzim.writer import Creator, Hint

from app.domain.models import Resolution
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob
from app.knowledge.topic_articles import NONE_FOUND, ask_topic_articles
from app.llm.prompts import get_prompt
from app.main import create_app
from app.service import CompendiumService
from app.settings import Settings
from app.sources.zim.registry import NAMED_ORIGIN, ZimRegistry, misses_topic
from tests.conftest import HtmlItem
from tests.test_article_choice import by_prompt
from tests.test_article_choice_thorough import LIST, refuse
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

ARTICLES_PROMPT = get_prompt("topic_articles")
SET = {
    "Liste deutschsprachiger Lyriker": "<p>Diese Liste nennt Lyriker, die in deutscher Sprache schrieben.</p>",
    "Deutschsprachige Literatur": "<p>Die deutschsprachige Literatur umfasst die Werke in deutscher Sprache.</p>",
    "Johann Wolfgang von Goethe": "<p>Johann Wolfgang von Goethe war ein deutscher Dichter und Naturforscher.</p>",
    "Goethe (Begriffsklärung)": LIST.format(
        items='<li><a href="Johann_Wolfgang_von_Goethe" title="Johann Wolfgang von Goethe">Goethe</a>, Dichter</li>'
    ),
}
REDIRECTS = [
    ("Deutsche_Dichter", "Deutsche Dichter", "Liste_deutschsprachiger_Lyriker"),
    ("Goethe", "Goethe", "Johann_Wolfgang_von_Goethe"),
]


def asking(articles: Any, choice: Any = None, notes: dict[str, int] | None = None) -> Callable[[dict[str, Any]], str]:
    """One fake b-api for every call of article_choice llm: N gets ``articles``, the hit check its notes, the choice
    of the article ``choice``."""
    others = by_prompt({"wahl": 1} if choice is None else choice, notes)
    answer = articles if isinstance(articles, str) else json.dumps(articles)
    return lambda body: answer if body["messages"][0]["content"] == ARTICLES_PROMPT.system else others(body)


def job_for(fake: FakeBApi, per_request: int = 100_000) -> ArticleChoiceJob:
    gateway = make_gateway(fake, per_request=per_request)
    return ArticleChoiceJob(gateway.client, gateway.open_budget())


@pytest.fixture(scope="module")
def sets(tmp_path_factory: pytest.TempPathFactory) -> ZimRegistry:
    path = tmp_path_factory.mktemp("zim") / "wikipedia_de_sammel_2026-01.zim"
    with Creator(str(path)) as creator:
        creator.set_mainpath("Deutschsprachige_Literatur")
        for title, body in SET.items():
            html = f"<html><head><title>{title}</title></head><body>{body}</body></html>"
            creator.add_item(HtmlItem(title.replace(" ", "_"), title, html))
        for entry, title, target in REDIRECTS:
            creator.add_redirection(entry, title, target, {Hint.FRONT_ARTICLE: True})
    return ZimRegistry([path])


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


# -- where the overview may replace the main article --------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "title", "missed"),
    [
        ("suggestion", "Geometrische Optik", True),
        ("search", "Augenoptiker", True),
        ("title", "Liste deutschsprachiger Lyriker", True),
        (None, None, True),
        ("title", "Optik", False),
        ("variant", "Optik", False),
        ("disambiguation", "Optik", False),
    ],
)
def test_the_rules_miss_a_topic_with_a_guess_a_list_page_or_nothing(
    method: str | None, title: str | None, missed: bool
) -> None:
    assert misses_topic(Resolution(query="x", normalized="x", title=title, method=method)) is missed


def test_the_overview_replaces_a_list_page_the_rules_reached(sets: ZimRegistry) -> None:
    rules = sets.resolve_topic("Deutsche Dichter")
    assert rules.title == "Liste deutschsprachiger Lyriker" and rules.confident, "a redirect to a list, as in dewiki"
    resolution = sets.resolve_topic("Deutsche Dichter", chooser=refuse, overview="Deutschsprachige Literatur")
    assert resolution.title == "Deutschsprachige Literatur" and resolution.method == "llm" and not resolution.confident
    assert resolution.alternatives[0] == "Liste deutschsprachiger Lyriker", "the rules' article stays visible"


def test_the_overview_leaves_an_article_the_rules_hit(sets: ZimRegistry) -> None:
    resolution = sets.resolve_topic("Deutschsprachige Literatur", chooser=refuse, overview="Goethe")
    assert resolution.title == "Deutschsprachige Literatur" and resolution.method == "title"


# -- the question ----------------------------------------------------------------------------------------------------


def test_n_names_the_overview_first_and_keeps_only_articles_of_the_archive(sets: ZimRegistry) -> None:
    named = ["Goethe", "Goethe (Begriffsklärung)", "Friedrich Schiller", "Johann Wolfgang von Goethe"]
    fake = FakeBApi(asking({"uebersicht": "Deutschsprachige Literatur", "artikel": named}))
    archive = sets.primary_archive
    assert archive is not None
    report = ask_topic_articles(job_for(fake), archive, "deutsche Dichter")

    # a redirect counts as its target; a disambiguation page, a title the archive lacks and a repeat do not
    assert report.found == ["Deutschsprachige Literatur", "Johann Wolfgang von Goethe"]
    assert report.overview == "Deutschsprachige Literatur" and report.named == named and report.fallback is None
    assert report.calls == 1 and report.total_tokens == 24 and report.prompts == [ARTICLES_PROMPT.tag]
    question = fake.bodies[0]["messages"][1]["content"]
    assert question.startswith("Thema: deutsche Dichter\n") and "bis zu 8 Artikel" in question, "M37 word for word"


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ("Leider kenne ich keine passenden Artikel.", UNREADABLE),
        ({"uebersicht": "Gibt es nicht", "artikel": ["Auch nicht"]}, NONE_FOUND),
        ({"uebersicht": "", "artikel": []}, NONE_FOUND),
    ],
)
def test_without_an_article_of_the_archive_n_says_why(sets: ZimRegistry, answer: Any, reason: str) -> None:
    archive = sets.primary_archive
    assert archive is not None
    report = ask_topic_articles(job_for(FakeBApi(asking(answer))), archive, "deutsche Dichter")
    assert report.found == [] and report.fallback == reason


def test_a_budget_too_small_for_n_is_a_fallback_without_a_call(sets: ZimRegistry) -> None:
    fake = FakeBApi(asking({"uebersicht": "Deutschsprachige Literatur", "artikel": []}))
    archive = sets.primary_archive
    assert archive is not None
    report = ask_topic_articles(job_for(fake, per_request=100), archive, "deutsche Dichter")
    assert fake.bodies == [] and report.found == [] and "Token-Budget" in (report.fallback or "")


# -- the corpus ------------------------------------------------------------------------------------------------------


def test_the_named_articles_replace_linked_sub_articles_and_full_text_hits(registry: ZimRegistry) -> None:
    named = ["Optik", "Technische Optik", "Lichtmikroskop"]
    sources = registry.build_corpus(registry.resolve_topic("Optik"), slots=[], max_articles=8, named=named)
    assert [(s.title, s.origin) for s in sources] == [
        ("Optik", "primary"),
        ("Optik", "same_topic"),  # the Klexikon twin stays: it is the topic itself
        ("Technische Optik", NAMED_ORIGIN),
        ("Lichtmikroskop", NAMED_ORIGIN),
    ]


def test_max_articles_caps_the_named_articles(registry: ZimRegistry) -> None:
    named = ["Technische Optik", "Lichtmikroskop"]
    sources = registry.build_corpus(registry.resolve_topic("Optik"), slots=[], max_articles=3, named=named)
    assert [s.title for s in sources] == ["Optik", "Optik", "Technische Optik"]


# -- through the service ---------------------------------------------------------------------------------------------


def test_balanced_builds_the_corpus_from_the_articles_n_names(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(
        asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik", "Lichtmikroskop", "Gibt es nicht"]})
    )
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik", preset="balanced", parts=["world"]))  # type: ignore[arg-type]

    assert result.resolution.title == "Optik" and result.resolution.method == "title", "the rules hit it: it stays"
    # the main article, its Klexikon twin and the two named articles of the archive (their origin: /knowledge below)
    assert [s.title for s in result.sources] == ["Optik", "Optik", "Geometrische Optik", "Lichtmikroskop"]
    assert len(fake.bodies) == 1, "N alone: no hit check, and the rules were sure of the article"
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["used"] == "llm" and choice["needed"] and choice["articles_asked"]
    assert choice["articles_found"] == ["Optik", "Geometrische Optik", "Lichtmikroskop"]
    assert not choice["articles_main"] and choice["articles_fallback"] is None and choice["hits_checked"] == 0
    assert ARTICLES_PROMPT.tag in result.frontmatter["llm"]["prompts"]
    assert result.audit.llm_tokens == {"prompt": 20, "completion": 4, "total": 24, "calls": 1}


def test_n_replaces_the_main_article_where_the_rules_only_guess(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules = service.registry.resolve_topic("Geometrische")
    assert rules.method in {"suggestion", "search"}, "the sample archive has no article of that name"
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik", "Technische Optik"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Geometrische", preset="balanced", parts=["world"]))  # type: ignore[arg-type]

    assert result.resolution.title == "Optik" and result.resolution.method == "llm"
    assert result.resolution.alternatives[0] == rules.title, "the rules' guess stays visible"
    assert len(fake.bodies) == 1, "the overview decides: the choice among the rules' candidates is not asked"
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["articles_main"] and choice["chosen"] == "Optik" and choice["used"] == "llm"


def test_the_paragraphs_of_a_named_article_need_not_name_the_topic(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A linked sub-article or a hit keeps only paragraphs that carry the topic's stem; a named one keeps all, as in M37
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Sinfonie"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik", preset="balanced", parts=["world"]))  # type: ignore[arg-type]
    assert "Sinfonie" in [s.title for s in result.sources]


def test_an_unusable_answer_leaves_the_corpus_of_before(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(asking("kein JSON", notes={"Augenoptiker": 0}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik", preset="balanced", parts=["world"]))  # type: ignore[arg-type]

    assert "Augenoptiker" not in [s.title for s in result.sources], "the hit check ran as before"
    assert len(fake.bodies) == 2
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["articles_fallback"] == UNREADABLE and choice["articles_found"] == []
    # four linked sub-articles and two full-text hits, as without N (test_article_choice)
    assert choice["hits_checked"] == 6 and choice["hits_dropped"] == ["Augenoptiker"]
    assert choice["used"] == "llm", "the hit check decided"


def test_llm_free_asks_nothing(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Lichtmikroskop"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(GenerateRequest(topic="Optik", preset="llm-free", parts=["world"]))  # type: ignore[arg-type]
    assert fake.bodies == [] and result.audit.llm is None


def test_named_articles_that_carry_the_topic_are_sub_topics_of_part_two(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik", "Lichtmikroskop"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    _, _, job = service.article_choice_job("llm", None)
    prepared = service.prepare(GenerateRequest(topic="Optik", parts=["world"], article_choice="llm"), None, job)
    assert "Geometrische Optik" in prepared.subtopics and "Lichtmikroskop" not in prepared.subtopics


def test_knowledge_names_the_articles_a_compendium_builds_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik", "Lichtmikroskop"]}))
    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(fake, per_request=100_000))  # type: ignore[attr-defined]
    body = client.post("/api/v2/knowledge", json={"topic": "Optik", "preset": "balanced"}).json()

    assert [(a["title"], a["origin"]) for a in body["articles"]] == [
        ("Optik", "primary"),
        ("Optik", "same_topic"),
        ("Geometrische Optik", NAMED_ORIGIN),
        ("Lichtmikroskop", NAMED_ORIGIN),
    ]
    choice = body["article_choice"]
    assert choice["used"] == "llm" and choice["articles_found"] == ["Optik", "Geometrische Optik", "Lichtmikroskop"]
    assert choice["tokens"] == 24 and choice["hits_checked"] == 0
