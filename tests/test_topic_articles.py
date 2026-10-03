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

from app.domain.models import Resolution, SectionStatus
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob
from app.knowledge.corpus_sources import NAMED_ORIGIN, build_corpus
from app.knowledge.main_article import choose_main_article
from app.knowledge.resolution import misses_topic, resolve_topic
from app.knowledge.topic_articles import NO_PARTS, NONE_FOUND, ask_topic_articles
from app.llm.prompts import get_prompt
from app.main import create_app
from app.service import CompendiumService
from app.settings import Settings
from app.sources.wlo.part import node_topic
from app.sources.zim.registry import ZimRegistry
from tests.conftest import HtmlItem
from tests.test_article_choice import by_prompt
from tests.test_article_choice_thorough import LIST, refuse
from tests.test_llm_client import FakeBApi
from tests.test_main_article import STATIONS
from tests.test_pipeline_llm import answer_with_model_knowledge, make_gateway

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
    rules = resolve_topic(sets, "Deutsche Dichter")
    assert rules.title == "Liste deutschsprachiger Lyriker" and rules.confident, "a redirect to a list, as in dewiki"
    resolution = resolve_topic(sets, "Deutsche Dichter", chooser=refuse, overview="Deutschsprachige Literatur")
    assert resolution.title == "Deutschsprachige Literatur" and resolution.method == "llm" and not resolution.confident
    assert resolution.alternatives[0] == "Liste deutschsprachiger Lyriker", "the rules' article stays visible"


def test_the_overview_leaves_an_article_the_rules_hit(sets: ZimRegistry) -> None:
    resolution = resolve_topic(sets, "Deutschsprachige Literatur", chooser=refuse, overview="Goethe")
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


def test_an_overview_with_a_qualifier_the_archive_lacks_is_looked_up_without_it(sets: ZimRegistry) -> None:
    """M49 (V1a, 07 point 14): "Aufklärung (Philosophie)" is no article, "Aufklärung" is; a named overview the archive
    lacked let a member of the group stand in for it (M48: Immanuel Kant). Without the qualifier it is found."""
    archive = sets.primary_archive
    assert archive is not None
    found = ask_topic_articles(
        job_for(FakeBApi(asking({"uebersicht": "Deutschsprachige Literatur (Gesamtheit)", "artikel": ["Goethe"]}))),
        archive,
        "deutsche Dichter",
    )
    missing = ask_topic_articles(
        job_for(FakeBApi(asking({"uebersicht": "Gibt es nicht (Literatur)", "artikel": []}))),
        archive,
        "deutsche Dichter",
    )

    assert found.overview_title == "Deutschsprachige Literatur"
    assert found.found == ["Deutschsprachige Literatur", "Johann Wolfgang von Goethe"]
    assert missing.overview_title is None and missing.fallback == NONE_FOUND


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
    sources = build_corpus(registry, resolve_topic(registry, "Optik"), slots=[], max_articles=8, named=named)
    assert [(s.title, s.origin) for s in sources] == [
        ("Optik", "primary"),
        ("Optik", "same_topic"),  # the Klexikon twin stays: it is the topic itself
        ("Technische Optik", NAMED_ORIGIN),
        ("Lichtmikroskop", NAMED_ORIGIN),
    ]


def test_max_articles_caps_the_named_articles(registry: ZimRegistry) -> None:
    named = ["Technische Optik", "Lichtmikroskop"]
    sources = build_corpus(registry, resolve_topic(registry, "Optik"), slots=[], max_articles=3, named=named)
    assert [s.title for s in sources] == ["Optik", "Optik", "Technische Optik"]


# -- through the service ---------------------------------------------------------------------------------------------


def test_balanced_builds_the_corpus_from_the_articles_n_names(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(
        asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik", "Lichtmikroskop", "Gibt es nicht"]})
    )
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik", preset="balanced", parts=["world"]))

    assert result.resolution.title == "Optik" and result.resolution.method == "title", "the rules hit it: it stays"
    # the main article, its Klexikon twin and the two named articles of the archive (their origin: /knowledge below)
    assert [s.title for s in result.sources] == ["Optik", "Optik", "Geometrische Optik", "Lichtmikroskop"]
    assert len(fake.bodies) == 1, "N alone: no hit check, and the rules were sure of the article"
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["used"] == "llm" and choice["needed"] and choice["articles_asked"]
    assert choice["articles_found"] == ["Optik", "Geometrische Optik", "Lichtmikroskop"]
    assert not choice["articles_main"] and choice["articles_fallback"] is None and choice["hits_checked"] == 0
    assert choice["articles_overview"] == "Optik", "the overview the model named, as the archive has it"
    assert ARTICLES_PROMPT.tag in result.frontmatter["llm"]["prompts"]
    assert result.audit.llm_tokens == {"prompt": 20, "completion": 4, "total": 24, "calls": 1, "cached": 0}


def test_n_replaces_the_main_article_where_the_rules_only_guess(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules = resolve_topic(service.registry, "Geometrische")
    assert rules.method in {"suggestion", "search"}, "the sample archive has no article of that name"
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik", "Technische Optik"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Geometrische", preset="balanced", parts=["world"]))

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
    result = service.generate(GenerateRequest(topic="Optik", preset="balanced", parts=["world"]))
    assert "Sinfonie" in [s.title for s in result.sources]


def test_an_unusable_answer_leaves_the_corpus_of_before(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(asking("kein JSON", notes={"Augenoptiker": 0}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik", preset="balanced", parts=["world"]))

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
    result = service.generate(GenerateRequest(topic="Optik", preset="llm-free", parts=["world"]))
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


# -- after the review of D63 ---------------------------------------------------------------------------------------


def test_n_hears_the_subject_of_the_request(sets: ZimRegistry) -> None:
    # "Informatik: Baum" is a data structure, "Baum" alone a plant: the subject has to decide the parts as well
    fake = FakeBApi(asking({"uebersicht": "", "artikel": []}))
    archive = sets.primary_archive
    assert archive is not None
    ask_topic_articles(job_for(fake), archive, "Baum", subjects=["Informatik", "Mathematik"])
    assert fake.bodies[0]["messages"][1]["content"].splitlines()[0] == "Thema: Baum (Fach: Informatik, Mathematik)"


def test_a_compendium_passes_its_subject_to_n(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": []}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    request = GenerateRequest(topic="Optik", subject="Physik", preset="balanced", parts=["world"])
    service.generate(request)
    asked = [body for body in fake.bodies if body["messages"][0]["content"] == ARTICLES_PROMPT.system]
    assert asked[0]["messages"][1]["content"].splitlines()[0] == "Thema: Optik (Fach: Physik)"


def test_without_the_overview_in_the_archive_the_first_part_stands_in(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As measured in M37 and M39 ("Philosophen der Aufklärung" -> John Locke), and the audit says so
    fake = FakeBApi(asking({"uebersicht": "Geometrische Lehre", "artikel": ["Technische Optik", "Lichtmikroskop"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Geometrische", preset="balanced", parts=["world"]))

    assert result.resolution.title == "Technische Optik" and result.resolution.method == "llm"
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["articles_main"] and choice["articles_overview"] is None


def test_n_without_a_part_of_the_archive_leaves_the_side_articles_of_before(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Gibt es nicht"]}, notes={"Augenoptiker": 0}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik", preset="balanced", parts=["world"]))

    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["articles_found"] == ["Optik"] and choice["articles_fallback"] == NO_PARTS
    assert choice["hits_checked"] == 6 and choice["hits_dropped"] == ["Augenoptiker"], "linked and hits as before"
    assert len(fake.bodies) == 2


def test_the_corpus_keeps_its_side_articles_when_no_named_article_is_new(registry: ZimRegistry) -> None:
    sources = build_corpus(registry, resolve_topic(registry, "Optik"), slots=[], max_articles=8, named=["Optik"])
    origins = {s.origin for s in sources}
    assert "linked" in origins and NAMED_ORIGIN not in origins


def test_with_a_topic_and_a_material_n_is_asked_too(service: CompendiumService) -> None:
    node_question = get_prompt("node_topic_with_topic").system

    def answer(body: dict[str, Any]) -> str:
        system = body["messages"][0]["content"]
        if system == ARTICLES_PROMPT.system:
            return json.dumps({"uebersicht": "Optik", "artikel": ["Lichtmikroskop"]})
        return json.dumps({"titel": "Optik", "material": ""} if system == node_question else {"wahl": 1})

    chosen = choose_main_article(
        service.registry,
        service.subjects,
        "Optik",
        [node_topic(STATIONS)],
        node=STATIONS,
        job=job_for(FakeBApi(answer)),
    )
    assert chosen.resolution.title == "Optik", "the question on topic and material decides the article"
    assert chosen.articles is not None and chosen.articles.found == ["Optik", "Lichtmikroskop"]
    assert not chosen.articles.main


def test_named_articles_come_from_the_archive_they_were_found_in(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "Licht" is an article of the Klexikon sample only: its main article comes from there, N's titles from Wikipedia
    fake = FakeBApi(asking({"uebersicht": "Licht", "artikel": ["Optik", "Lichtmikroskop"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    _, _, job = service.article_choice_job("llm", None)
    prepared = service.prepare(GenerateRequest(topic="Licht", parts=["world"], article_choice="llm"), None, job)

    leading = service.registry.primary_archive
    assert leading is not None and prepared.resolution.project != leading.project
    named = [(s.title, s.project) for s in prepared.sources if s.origin == NAMED_ORIGIN]
    assert named == [("Optik", leading.project), ("Lichtmikroskop", leading.project)]


def test_a_failing_b_api_leaves_the_corpus_of_before(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Lichtmikroskop"]}), statuses=[500, 500, 500])
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik", preset="balanced", parts=["world"]))

    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert (choice["articles_fallback"] or "").startswith("b-api") and choice["articles_found"] == []
    assert choice["articles_asked"] and choice["hits_checked"] == 6, "the side articles of before, checked as before"


def test_best_quality_asks_n_and_checks_a_sure_word_with_meanings(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Lichtmikroskop"]}, choice={"wahl": 1}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    request = GenerateRequest(topic="Optik", preset="best-quality", matcher="hybrid_light", parts=["world"])
    result = service.generate(request)

    assert result.resolution.title == "Optik" and len(fake.bodies) == 2, "N, then the check of the sure word"
    assert result.audit.llm is not None
    choice = result.audit.llm["article_choice"]
    assert choice["asked"] and choice["articles_asked"] and not choice["articles_main"]
    assert "Lichtmikroskop" in [s.title for s in result.sources]


def test_knowledge_names_the_corpus_of_the_compendium(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    service = client.app.state.service  # type: ignore[attr-defined]
    fake = FakeBApi(asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik", "Lichtmikroskop"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100_000))
    body = client.post("/api/v2/knowledge", json={"topic": "Optik", "preset": "balanced"}).json()
    _, _, job = service.article_choice_job("llm", None)
    prepared = service.prepare(GenerateRequest(topic="Optik", parts=["world"], article_choice="llm"), None, job)
    assert [(a["title"], a["origin"]) for a in body["articles"]] == [(s.title, s.origin) for s in prepared.sources]


# -- V3: the hint on the profiles that write about the topic as asked (M49; 07, points 12e and 14) -------------------


@pytest.mark.parametrize(("said", "covers"), [(True, True), (False, False), ("ja", None)])
def test_n_says_whether_its_overview_covers_the_topic_as_asked(
    sets: ZimRegistry, said: Any, covers: bool | None
) -> None:
    fake = FakeBApi(asking({"uebersicht": "Deutschsprachige Literatur", "artikel": [], "deckt_ab": said}))
    archive = sets.primary_archive
    assert archive is not None
    report = ask_topic_articles(job_for(fake), archive, "deutsche Dichter")

    assert report.covers is covers
    assert ARTICLES_PROMPT.version == 2 and '"deckt_ab"' in fake.bodies[0]["messages"][1]["content"]


def test_a_part_standing_in_for_a_missing_overview_does_not_cover_the_topic(sets: ZimRegistry) -> None:
    """The model judged the overview it named; a member standing in for it covers a group in part at most (M48:
    Walther von der Vogelweide for "Dichter aus dem Mittelalter")."""
    answer = {"uebersicht": "Gibt es nicht", "artikel": ["Goethe"], "deckt_ab": True}
    archive = sets.primary_archive
    assert archive is not None
    report = ask_topic_articles(job_for(FakeBApi(asking(answer))), archive, "deutsche Dichter")

    assert report.overview_title is None and report.found == ["Johann Wolfgang von Goethe"] and report.covers is False


@pytest.mark.parametrize(("covers", "hinted"), [(False, True), (True, False)])
def test_a_topic_its_overview_covers_only_in_part_gets_a_hint_on_the_writing_profiles(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch, covers: bool, hinted: bool
) -> None:
    """N says whether its overview covers the topic as asked; where it does not, the check of a verbatim compendium
    names the topic and the profiles that write about it, at no further token. The heading stays the article (D12;
    Jan, 2026-10-02)."""
    answer = {"uebersicht": "Optik", "artikel": ["Geometrische Optik"], "deckt_ab": covers}
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(asking(answer)), per_request=100_000))
    result = service.generate(GenerateRequest(topic="Optik im Alltag", preset="balanced", parts=["world"]))

    assert result.audit.llm is not None and result.audit.llm["article_choice"]["articles_covers"] is covers
    assert (result.topic, result.resolution.title) == ("Optik im Alltag", "Optik")  # the heading as asked (D75)
    scope = [finding for finding in result.audit.lint if finding.rule == "topic-scope"]
    assert bool(scope) is hinted
    assert not scope or ("Optik im Alltag" in scope[0].message and "best-coverage-generated" in scope[0].message)


def test_without_an_llm_the_words_of_the_topic_decide_the_hint(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik in der Medizin", preset="llm-free", parts=["world"]))

    assert (result.resolution.title, result.resolution.method) == ("Optik", "search")
    assert result.topic == "Optik in der Medizin" and "# Kompendium: Optik in der Medizin\n" in result.markdown
    scope = [finding for finding in result.audit.lint if finding.rule == "topic-scope"]
    assert len(scope) == 1 and "„Optik in der Medizin“" in scope[0].message


def test_a_text_written_about_the_topic_as_asked_gets_no_hint(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik"], "deckt_ab": False})

    def answer(body: dict[str, Any]) -> str:
        writing = body["messages"][0]["content"].startswith("Du formulierst einen Baustein")
        return answer_with_model_knowledge(body) if writing else n(body)

    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(answer), per_request=200_000))
    request = GenerateRequest(
        topic="Optik im Alltag", article_choice="llm", generation="llm", enrichment="model-knowledge", parts=["world"]
    )
    result = service.generate(request)

    assert result.topic == "Optik im Alltag"
    assert "topic-scope" not in [finding.rule for finding in result.audit.lint]


def test_blocks_whose_writing_fell_back_get_the_hint_of_the_article_they_print(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit 2026-10-02, A10: the blocks with evidence fail and keep the article's paragraphs, those without are
    written from model knowledge; once one block was written, the check said nothing of the verbatim ones."""
    n = asking({"uebersicht": "Optik", "artikel": ["Geometrische Optik"], "deckt_ab": False})
    gateway = make_gateway(FakeBApi(n), per_request=200_000)
    write = gateway.synthesizer.write_section

    def failing_with_evidence(slot: Any, scored: Any, *args: Any, **kwargs: Any) -> Any:
        if scored:
            raise RuntimeError("kaputt")
        return write(slot, scored, *args, **kwargs)

    monkeypatch.setattr(gateway.synthesizer, "write_section", failing_with_evidence)
    monkeypatch.setattr(service, "llm", gateway)
    request = GenerateRequest(
        topic="Optik im Alltag", article_choice="llm", generation="llm", enrichment="model-knowledge", parts=["world"]
    )
    result = service.generate(request)

    assert result.enrichment == "model-knowledge"  # the LLM wrote blocks
    verbatim = [s for s in result.sections if s.text and s.status is SectionStatus.EXTRACTIVE]
    scope = [finding for finding in result.audit.lint if finding.rule == "topic-scope"]
    assert verbatim and len(scope) == 1
    assert scope[0].message.startswith(f"{len(verbatim)} Bausteine geben den Artikel „Optik“ wörtlich wieder")


@pytest.mark.parametrize("topic", ["Optik in Klasse 7", "Optiken"])
def test_n_judges_its_own_overview_not_the_article_the_rules_kept(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch, topic: str
) -> None:
    """Review 2026-10-02: N named an overview the archive lacks, a part stood in (covers false), but the rules' article
    stayed - the topic's own, without its level or in another form - and the hint said the text missed the topic."""
    answer = {"uebersicht": "Gibt es nicht", "artikel": ["Geometrische Optik"], "deckt_ab": True}
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(asking(answer)), per_request=100_000))
    result = service.generate(GenerateRequest(topic=topic, preset="balanced", parts=["world"]))

    assert result.resolution.title == "Optik"
    assert result.audit.llm is not None and result.audit.llm["article_choice"]["articles_covers"] is False
    assert "topic-scope" not in [finding.rule for finding in result.audit.lint]
