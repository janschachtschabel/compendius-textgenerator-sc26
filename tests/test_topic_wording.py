"""The topic the writing profiles write about (Jan, 2026-10-02, D72): a text in place of a topic is worded by the model.

Jan: "wenn das thema zu lang ist oder eine texteingabe war sollte in den beiden profilen die ki das thema passend zum
input formulieren", and: a node - a material or a collection - can stand in for the topic or come with it ("dies kann
ersatzweise zum thema oder gemeinsam mit dem thema als input erfolgen"). The 123 topics the project knows - the gold
queries of the article choice, the group and mixed topics of M37, the topics of M48 - have at most five words and 37
characters and no question or exclamation mark, so a topic of more than six words, more than 60 characters or a
sentence's punctuation is a text; the metadata of a node without a topic always are.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob
from app.knowledge.topic_wording import (
    LONG,
    METADATA,
    SENTENCE,
    TOO_LONG_ANSWER,
    TopicWordingReport,
    metadata_input,
    needs_wording,
    word_topic,
    wording_request,
)
from app.llm.prompts import get_prompt
from app.sources.wlo.models import NodeInfo
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

ROOT = Path(__file__).resolve().parents[1]
GROUPS = [  # M37 and M48: groups, mixed topics and topics with an aspect
    "Deutsche Dichter",
    "Maler des Impressionismus",
    "Komponisten der Klassik",
    "Philosophen der Aufklärung",
    "Dichter aus dem Mittelalter",
    "Planeten des Sonnensystems",
    "Märchen der Brüder Grimm",
    "Frauen in der Wissenschaft",
    "Mathematik in der Musik",
    "Klimawandel und Landwirtschaft",
    "Erfindungen der Industrialisierung",
    "Nobelpreisträger für Physik",
    "OER-Förderungen",
    "Inklusion im Sportunterricht",
    "Künstliche Intelligenz im Unterricht",
]


def gold_queries() -> list[str]:
    queries: list[str] = []
    for path in sorted((ROOT / "eval" / "artikelwahl").glob("hauptartikel*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        queries += [entry["anfrage"] for entry in data.get("anfragen") or []]
    return queries


def job(fake: FakeBApi) -> ArticleChoiceJob:
    gateway = make_gateway(fake, per_request=100_000)
    return ArticleChoiceJob(gateway.client, gateway.open_budget())


def answering(answer: object) -> FakeBApi:
    return FakeBApi(lambda body: answer if isinstance(answer, str) else json.dumps(answer))


def test_no_topic_the_project_knows_counts_as_a_text() -> None:
    topics = [*gold_queries(), *GROUPS]
    assert len(topics) > 100
    assert [topic for topic in topics if needs_wording(topic)] == []


@pytest.mark.parametrize(
    "text",
    [
        "Wie funktioniert die Photosynthese?",
        "Photosynthese erklären!",
        "Die Schüler sollen lernen, wie Pflanzen Energie gewinnen. Danach folgt ein Versuch.",
        "Pflanzen gewinnen ihre Energie aus Licht.",
    ],
)
def test_a_question_or_a_sentence_is_a_text(text: str) -> None:
    assert needs_wording(text) == SENTENCE


@pytest.mark.parametrize(
    "text",
    [
        "Material zur Lichtbrechung für meine achte Klasse mit Experimenten",
        "Lichtbrechung an Grenzflächen zwischen Luft, Wasser und Glas im Alltag",
        "Elektrizitätsversorgung, Netzstabilität und Speichertechnologien Deutschlands",
    ],
)
def test_more_than_six_words_or_sixty_characters_is_a_text(text: str) -> None:
    assert needs_wording(text) == LONG


@pytest.mark.parametrize("topic", ["Kunst im 19. Jahrhundert", "St. Petersburg", "Dr. Faustus", "Physik: Optik"])
def test_an_ordinal_an_abbreviation_or_a_subject_prefix_is_no_sentence(topic: str) -> None:
    assert needs_wording(topic) is None


def test_the_model_words_the_topic_of_a_text() -> None:
    fake = answering({"thema": "Energiegewinnung der Pflanzen"})
    report = TopicWordingReport(source="Thema", reason=SENTENCE)

    worded = word_topic(job(fake), "Wie gewinnen Pflanzen ihre Energie aus dem Licht?", report)

    assert worded == "Energiegewinnung der Pflanzen"
    assert report.topic == worded and report.fallback is None
    assert report.calls == 1 and report.prompts == [get_prompt("topic_wording").tag]
    assert "Wie gewinnen Pflanzen ihre Energie aus dem Licht?" in fake.bodies[0]["messages"][1]["content"]


def test_quotes_and_blanks_around_the_worded_topic_go() -> None:
    fake = answering({"thema": " „Energiegewinnung   der Pflanzen“ "})

    assert word_topic(job(fake), "Wie gewinnen Pflanzen Energie?", TopicWordingReport()) == (
        "Energiegewinnung der Pflanzen"
    )


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ("kein JSON", UNREADABLE),
        ({"thema": ""}, UNREADABLE),
        ({"thema": 7}, UNREADABLE),
        (
            {"thema": "Ein sehr langer Titel mit viel zu vielen Wörtern für ein Thema eines Kompendiums"},
            TOO_LONG_ANSWER,
        ),
    ],
)
def test_an_answer_that_is_no_topic_leaves_the_topic_as_asked(answer: object, reason: str) -> None:
    report = TopicWordingReport()

    assert word_topic(job(answering(answer)), "Wie gewinnen Pflanzen Energie?", report) is None
    assert report.fallback == reason and report.topic is None


def test_a_call_the_budget_turns_away_names_why() -> None:
    gateway = make_gateway(answering({"thema": "Energie der Pflanzen"}), per_request=10)
    report = TopicWordingReport()

    assert (
        word_topic(ArticleChoiceJob(gateway.client, gateway.open_budget()), "Wie gewinnen Pflanzen Energie?", report)
        is None
    )
    assert report.fallback and report.topic is None


def node(kind: str = "material", title: str = "Stationsarbeit zur Optik", description: str = "") -> NodeInfo:
    return NodeInfo(
        node_id="0",
        kind=kind,
        title=title,
        description=description or "Acht Stationen zu Spiegelung und Brechung.",
        keywords=("Licht", "Spiegel"),
        subject_uris=(),
        subject_labels=("Physik",),
        educational_contexts=("Sekundarstufe I",),
        url="",
    )


def test_a_node_brings_its_title_subjects_keywords_and_description() -> None:
    text = metadata_input(node(description="Acht Stationen zu Spiegelung und Brechung. " * 100))

    assert text.startswith(
        "Titel des Materials: Stationsarbeit zur Optik\nFächer: Physik\nSchlagwörter: Licht, Spiegel"
    )
    assert len(text) < 1_700  # the description cut as for the material's article (D47)
    assert metadata_input(node(kind="collection", title="Optik")).startswith("Titel der Sammlung: Optik\n")


def test_a_short_topic_stands_as_asked_with_or_without_a_node() -> None:
    assert wording_request("Optik", None) is None
    assert wording_request("Komponisten der Klassik", node()) is None


def test_a_text_as_topic_is_worded_with_the_node_beside_it() -> None:
    asked = "Wie funktioniert die Brechung des Lichts an einer Linse?"

    alone = wording_request(asked, None)
    beside = wording_request(asked, node())

    assert alone is not None and alone.source == "Thema" and alone.reason == SENTENCE
    assert alone.text == f"Anfrage der Lehrkraft: {asked}"
    assert beside is not None and beside.source == "Thema mit Material"
    assert beside.text.startswith(
        f"Anfrage der Lehrkraft: {asked}\n\nDazu angegeben:\nTitel des Materials: Stationsarbeit"
    )


@pytest.mark.parametrize(("kind", "source"), [("material", "Material"), ("collection", "Sammlung")])
def test_a_node_without_a_topic_is_always_worded_from_its_metadata(kind: str, source: str) -> None:
    wording = wording_request(None, node(kind=kind))

    assert wording is not None and wording.source == source and wording.reason == METADATA
    assert wording.text == metadata_input(node(kind=kind))


def test_nothing_to_word_without_topic_and_node() -> None:
    assert wording_request(None, None) is None
