"""The article a request builds on, from its topic, its node or both (D12, D45, D47).

A material without a topic gets its article from the rules over its title and description, or from the LLM with
article_choice llm (M21, M23). A topic sent along with a material leads; the material adds its own article, which
the corpus takes when it links with the main article, and with article_choice llm one question hears both. A
collection keeps its title as the topic, as before.
"""

from __future__ import annotations

import json
from typing import Any

from app.knowledge.article_choice import ArticleChoiceJob
from app.knowledge.main_article import choose_main_article
from app.service import CompendiumService
from app.sources.wlo.models import NodeInfo
from app.sources.wlo.part import node_topic
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

DISCIPLINE = "http://w3id.org/openeduhub/vocabs/discipline/"
STATIONS = NodeInfo(  # the material of the staging fixture
    node_id="ac66224b-42b0-4676-a53d-71b058dc780b",
    kind="material",
    title="Stationsarbeit zur Optik",
    description="An sechs Stationen untersuchen Lernende Aufbau und Funktion des Auges: Netzhaut, Pupille und Linse.",
    keywords=("Auge", "Netzhaut", "Pupille", "Linse", "Lochkamera", "Stationenlernen"),
    subject_uris=(DISCIPLINE + "080", DISCIPLINE + "460"),
    subject_labels=("Biologie", "Physik"),
    educational_contexts=("Sekundarstufe I",),
    url="https://www.tutory.de/entdecken/dokument/stationsarbeit-zur-optik-1",
)
EXAM = NodeInfo(
    node_id="11111111-2222-4333-8444-555555555555",
    kind="material",
    title="Klassenarbeit Nr. 3",
    description="Aufgaben zum Wiederholen vor den Ferien.",
    keywords=(),
    subject_uris=(),
    subject_labels=(),
    educational_contexts=(),
    url="",
)


def job(answer: Any, per_request: int = 100_000) -> tuple[ArticleChoiceJob, FakeBApi]:
    fake = FakeBApi(lambda body: answer if isinstance(answer, str) else json.dumps(answer))
    gateway = make_gateway(fake, per_request=per_request)
    return ArticleChoiceJob(gateway.client, gateway.open_budget()), fake


def choose(service: CompendiumService, topic: str | None, node: NodeInfo | None, **options: Any) -> Any:
    derived = [node_topic(node)] if node is not None else []
    return choose_main_article(service.registry, service.subjects, topic, derived, node=node, **options)


# -- a material without a topic ------------------------------------------------------------------------------------
def test_the_rules_find_the_article_of_a_material_in_its_title_and_description(service: CompendiumService) -> None:
    chosen = choose(service, None, STATIONS)
    assert chosen.resolution.title == "Optik"
    report = chosen.node
    assert report is not None and report.way == "rules" and report.entities == ["Optik", "Linse"]
    assert report.calls == 0 and chosen.material is None
    assert chosen.resolution.query == "Stationsarbeit zur Optik", "the resolution still shows what came in"


def test_a_material_the_rules_find_no_article_for_has_none(service: CompendiumService) -> None:
    chosen = choose(service, None, EXAM)
    assert not chosen.resolution.resolved
    assert chosen.node is not None and chosen.node.entities == [] and chosen.node.way == "rules"


def test_with_article_choice_llm_the_model_names_the_article(service: CompendiumService) -> None:
    ask, fake = job({"titel": "Geometrische Optik"})
    chosen = choose(service, None, STATIONS, job=ask)
    assert chosen.resolution.title == "Geometrische Optik" and len(fake.bodies) == 1
    assert chosen.node is not None and chosen.node.way == "llm" and chosen.node.named == "Geometrische Optik"
    assert chosen.node.entities == [], "the rules were not needed"


def test_a_material_the_model_sees_no_subject_topic_in_has_no_article(service: CompendiumService) -> None:
    ask, _ = job({"titel": ""})
    chosen = choose(service, None, STATIONS, job=ask)
    assert not chosen.resolution.resolved and chosen.node is not None and chosen.node.named == ""


def test_a_title_the_archive_lacks_or_an_unusable_model_leaves_it_to_the_rules(service: CompendiumService) -> None:
    ask, _ = job({"titel": "Qwertzuiopü"})
    missing = choose(service, None, STATIONS, job=ask)
    assert missing.resolution.title == "Optik" and missing.node is not None
    assert missing.node.way == "rules" and missing.node.fallback == "genannter Titel ist kein Artikel des Archivs"
    ask, _ = job({"titel": "Geometrische Optik"}, per_request=10)
    skipped = choose(service, None, STATIONS, job=ask)
    assert skipped.resolution.title == "Optik" and skipped.node is not None and skipped.node.fallback is not None


def test_a_named_title_only_the_search_reaches_counts_as_missing(service: CompendiumService) -> None:
    """As for the article choice (D35), the archive has to have the title the model names (M25).

    Resolved like a topic, "Mikroskopie mit Licht" reaches Lichtmikroskop through the full-text search; on the
    second material sample such names ended at "Engelmannscher Bakterienversuch" and "Polen in Island".
    """
    ask, _ = job({"titel": "Mikroskopie mit Licht"})
    chosen = choose(service, None, STATIONS, job=ask)
    assert chosen.resolution.title == "Optik" and chosen.node is not None and chosen.node.way == "rules"
    assert chosen.node.fallback == "genannter Titel ist kein Artikel des Archivs"


def test_a_named_redirect_counts_as_its_article(service: CompendiumService) -> None:
    ask, _ = job({"titel": "Lichtlehre"})
    chosen = choose(service, None, STATIONS, job=ask)
    assert chosen.resolution.title == "Optik" and chosen.node is not None and chosen.node.way == "llm"


# -- a topic and a material ----------------------------------------------------------------------------------------
def test_the_topic_leads_and_the_rules_name_the_material_article(service: CompendiumService) -> None:
    chosen = choose(service, "Geometrische Optik", STATIONS)
    assert chosen.resolution.title == "Geometrische Optik" and chosen.material == "Optik"
    assert chosen.node is not None and chosen.node.way == "rules" and chosen.node.material == "Optik"


def test_with_article_choice_llm_one_question_hears_topic_and_material(service: CompendiumService) -> None:
    ask, fake = job({"titel": "Geometrische Optik", "material": "Optik"})
    chosen = choose(service, "Geometrische Optik", STATIONS, job=ask)
    assert chosen.resolution.title == "Geometrische Optik" and chosen.material == "Optik"
    assert len(fake.bodies) == 1, "the sure topic needs no second call"
    assert fake.bodies[0]["messages"][1]["content"].startswith("Thema der Lehrkraft: Geometrische Optik\n")


def test_a_material_article_the_archive_does_not_have_is_none(service: CompendiumService) -> None:
    ask, _ = job({"titel": "Geometrische Optik", "material": "Mikroskopie mit Licht"})
    chosen = choose(service, "Geometrische Optik", STATIONS, job=ask)
    assert chosen.resolution.title == "Geometrische Optik" and chosen.material is None


def test_the_model_may_overrule_the_topic(service: CompendiumService) -> None:
    ask, _ = job({"titel": "Technische Optik", "material": ""})
    chosen = choose(service, "Optik", STATIONS, job=ask)
    assert chosen.resolution.title == "Technische Optik" and chosen.material is None


# -- as before -----------------------------------------------------------------------------------------------------
def test_a_collection_keeps_its_title_as_the_topic(service: CompendiumService) -> None:
    collection = NodeInfo(**{**STATIONS.__dict__, "kind": "collection", "title": "Optik"})
    chosen = choose(service, None, collection)
    assert chosen.resolution.title == "Optik" and chosen.node is None


def test_a_topic_alone_resolves_as_before(service: CompendiumService) -> None:
    chosen = choose_main_article(service.registry, service.subjects, "Physik: Optik", [])
    assert chosen.resolution.title == "Optik" and chosen.subjects == ["Physik"] and chosen.node is None


def test_an_article_the_rules_confirm_is_resolved_by_its_own_title(service: CompendiumService) -> None:
    """The title "Mikroskop" reaches Lichtmikroskop only through the search; the description names it, so the rule
    takes it - and the resolution then names the article, not the material's title, and is no longer a guess."""
    microscope = NodeInfo(**{**STATIONS.__dict__, "title": "Mikroskop", "description": "Mit dem Lichtmikroskop."})
    chosen = choose(service, None, microscope)
    assert chosen.resolution.title == "Lichtmikroskop" and chosen.resolution.method == "title"
    assert chosen.normalized.topic == "Lichtmikroskop" and chosen.resolution.normalized == "Lichtmikroskop"
