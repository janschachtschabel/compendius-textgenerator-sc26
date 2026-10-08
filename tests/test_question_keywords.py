"""The keywords of a question for the rules (M73): without an LLM a question went whole into the full-text search and
found "Mond" for the rainbow; its keywords, tried in the order it names them, find the article."""

from __future__ import annotations

from typing import Any

import pytest

from app.compendium.errors import TopicNotFoundError
from app.domain.models import Resolution
from app.domain.requests import GenerateRequest
from app.knowledge import main_article
from app.knowledge import question as question_module
from app.knowledge.question import MAX_KEYWORDS, keywords, resolve_by_keywords
from app.service import CompendiumService
from app.sources.zim.archive import ZimArchive


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


def test_a_keyword_is_looked_up_by_its_title_without_suggestions_or_a_full_text_search(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a keyword that names an article counts; its suggestions and full-text hits were sought and thrown away,
    2,851 searches for one topic of 299 characters (review of 2026-10-08)."""
    asked: list[str] = []
    for name in ("suggest", "search"):
        original = getattr(ZimArchive, name)

        def spy(archive: ZimArchive, *args: Any, _original: Any = original, _name: str = name) -> Any:
            asked.append(_name)
            return _original(archive, *args)

        monkeypatch.setattr(ZimArchive, name, spy)

    resolution = resolve_by_keywords(service.registry, "Welche Rolle spielen Zauberwürfelfabriken beim Regenbogen?")

    assert resolution is not None and resolution.title == "Regenbogen" and asked == []


def test_no_more_keywords_are_tried_than_a_question_names(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 60 questions of M73 name at most 15 keywords; a list of capitalised words makes hundreds."""
    planets = (
        "Planeten Sonnensystem Merkur Venus Erde Mars Jupiter Saturn Uranus Neptun Zwergplaneten Pluto Ceres Monde"
    )
    tried: list[str] = []
    original = question_module.resolve_topic

    def counting(registry: Any, word: str, **options: Any) -> Any:
        tried.append(word)
        return original(registry, word, **options)

    monkeypatch.setattr(question_module, "resolve_topic", counting)

    resolve_by_keywords(service.registry, planets)

    assert len(keywords(planets)) > MAX_KEYWORDS and len(tried) == MAX_KEYWORDS


def test_the_article_of_a_keyword_is_shown_as_a_guess_beside_what_the_rules_guessed(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M73: of 60 questions 2 articles were foreign and 5 better before; the review page showed a keyword's article as
    an exact title, sure, and no unsure hit to check (review of 2026-10-08)."""
    question = "Wie entsteht ein Regenbogen und warum ist er gekrümmt?"
    real = main_article.resolve_topic

    def rules(registry: Any, topic: str, **options: Any) -> Resolution:
        if topic != question:
            return real(registry, topic, **options)
        return Resolution(
            query=topic, normalized=topic, title="Optik", path="Optik", method="search"
        )  # a full-text hit

    monkeypatch.setattr(main_article, "resolve_topic", rules)

    resolution = service.prepare(GenerateRequest(topic=question, parts=["world"], preset="llm-free")).resolution

    assert (resolution.title, resolution.confident, resolution.alternatives[:1]) == ("Regenbogen", False, ["Optik"])


def test_a_sentence_the_rules_name_exactly_keeps_their_article(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only where the rules guessed do the keywords decide; the test with "Optik" above never reached their path, so
    the condition could go unnoticed (review of 2026-10-08)."""
    sentence = "Wie breitet sich das Licht in der Optik aus und warum?"
    real = main_article.resolve_topic

    def rules(registry: Any, topic: str, **options: Any) -> Resolution:
        if topic != sentence:
            return real(registry, topic, **options)
        return Resolution(query=topic, normalized=topic, title="Optik", path="Optik", method="title", confident=True)

    monkeypatch.setattr(main_article, "resolve_topic", rules)

    resolution = service.prepare(GenerateRequest(topic=sentence, parts=["world"], preset="llm-free")).resolution

    assert (resolution.title, resolution.method, resolution.confident) == ("Optik", "title", True)
