"""The keywords of a question for the rules (M73): without an LLM a question went whole into the full-text search and
found "Mond" for the rainbow; its keywords, tried in the order it names them, find the article."""

from __future__ import annotations

import pytest

from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.knowledge.question import keywords
from app.service import CompendiumService


@pytest.mark.parametrize(
    ("question", "first"),
    [
        ("Wie entsteht ein Regenbogen und warum ist er gekrümmt?", "Regenbogen"),
        ("Was passiert bei der Verdauung im menschlichen Körper?", "Verdauung"),
        ("Die Entstehung der Weimarer Republik nach dem Ersten Weltkrieg", "Weimarer Republik"),
        ("Welche Tiere leben im Wattenmeer?", "Wattenmeer"),
        ("Welche Aufgaben hat das Bundesverfassungsgericht?", "Bundesverfassungsgericht"),
        ("Erkläre den Unterschied zwischen Wetter und Klima", "Wetter und Klima"),
    ],
)
def test_the_first_keyword_is_the_first_thing_the_question_names(question: str, first: str) -> None:
    assert keywords(question)[0] == first


def test_an_adjective_and_its_noun_come_in_the_forms_of_a_title() -> None:
    assert "Nachhaltige Landwirtschaft" in keywords("Was versteht man unter nachhaltiger Landwirtschaft?")
    assert "Erster Weltkrieg" in keywords("Die Ursachen des Ersten Weltkriegs für eine 9. Klasse")
    assert "Dreißigjähriger Krieg" in keywords("Welche Ursachen hatte der Dreißigjährige Krieg?")


def test_a_question_without_a_noun_has_no_keyword() -> None:
    assert keywords("Wie kann man das erklären?") == []


def test_without_an_llm_a_question_finds_its_article_by_a_keyword(service: CompendiumService) -> None:
    question = "Wie entsteht ein Regenbogen und warum ist er gekrümmt?"
    prepared = service.prepare(GenerateRequest(topic=question, parts=["world"], preset="llm-free"))

    assert prepared.resolution.title == "Regenbogen" and prepared.resolution.method in {"title", "variant"}
    assert prepared.resolution.query == question  # the question stays what was asked
    assert prepared.asked_topic == question


def test_a_topic_the_rules_resolve_keeps_its_article(service: CompendiumService) -> None:
    prepared = service.prepare(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))
    assert prepared.resolution.title == "Optik" and prepared.resolution.method == "title"


def test_a_short_topic_keeps_what_the_rules_found(service: CompendiumService) -> None:
    """On short topics the keywords changed 41 of 195 topics of M63, as often for the worse as for the better: they
    stay with the rules; only a text in place of a topic gets its keywords (D72)."""
    with pytest.raises(TopicNotFoundError):  # the rules find none; the keywords would have found "Regenbogen"
        service.prepare(GenerateRequest(topic="Regenbogen über der Brille", parts=["world"], preset="llm-free"))


def test_runs_are_tried_down_to_two_words_and_a_pronoun_is_no_keyword() -> None:
    assert keywords("Weimarer Republik Krisenjahre")[:2] == [
        "Weimarer Republik Krisenjahre",
        "Weimarer Republik Krisenjahr",
    ]
    assert "Weimarer Republik" in keywords("Weimarer Republik Krisenjahre")
    assert keywords("Ich möchte mit meiner Klasse über Vulkane sprechen")[0] == "Vulkane"
