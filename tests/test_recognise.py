"""Recognising entities in a text (docs/umbau.md, U3): two ways that do not depend on each other.

The model finds names, the archives find terms that have an article. Either may be missing - no spaCy model,
no archives - and the other still answers. Nothing here touches the compendium path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.knowledge.recognise import Mention, load_spacy, mentions_from_ner, mentions_from_titles, merge
from app.sources.zim.registry import ZimRegistry

TEXT = "Ernst Abbe entwickelte in Jena das Lichtmikroskop und die Geometrische Optik."


@dataclass
class FakeEnt:
    text: str
    start_char: int
    end_char: int
    label_: str


@dataclass
class FakeDoc:
    ents: list[FakeEnt]


def fake_nlp(text: str) -> FakeDoc:
    """A stand-in for the spaCy pipeline: the tests pin our handling, not the model's quality."""
    return FakeDoc(ents=[FakeEnt("Ernst Abbe", 0, 10, "PER"), FakeEnt("Jena", 26, 30, "LOC")])


def test_the_model_gives_names_with_their_place_in_the_text() -> None:
    found = mentions_from_ner(fake_nlp, TEXT)
    assert [(m.text, m.kind, m.source) for m in found] == [
        ("Ernst Abbe", "PER", "ner"),
        ("Jena", "LOC", "ner"),
    ]
    assert TEXT[found[0].start : found[0].end] == "Ernst Abbe"


def test_without_a_model_there_is_nothing_to_recognise(tmp_path: Path) -> None:
    assert load_spacy("") is None
    assert load_spacy(str(tmp_path / "kein-modell")) is None


def test_the_archives_find_the_terms_that_have_an_article(registry: ZimRegistry) -> None:
    found = mentions_from_titles(registry.archives, TEXT)
    titles = {mention.text for mention in found}
    assert "Lichtmikroskop" in titles
    assert "Geometrische Optik" in titles, "the longer term wins over the bare Optik inside it"
    assert "Optik" not in titles
    assert "Jena" not in titles, "no article, so no term"
    assert {mention.source for mention in found} == {"dictionary"}


def test_without_archives_the_dictionary_stays_silent() -> None:
    assert mentions_from_titles([], TEXT) == []


def test_the_longer_mention_wins_over_one_inside_it() -> None:
    short = Mention(text="Optik", start=57, end=62, kind="", source="dictionary")
    long = Mention(text="Geometrische Optik", start=43, end=61, kind="", source="dictionary")
    assert merge([short, long]) == [long]


def test_of_two_equal_mentions_the_one_with_a_kind_wins() -> None:
    named = Mention(text="Ernst Abbe", start=0, end=10, kind="PER", source="ner")
    term = Mention(text="Ernst Abbe", start=0, end=10, kind="", source="dictionary")
    assert merge([term, named]) == [named]


def test_mentions_that_do_not_overlap_all_survive_in_reading_order() -> None:
    first = Mention(text="Ernst Abbe", start=0, end=10, kind="PER", source="ner")
    second = Mention(text="Lichtmikroskop", start=35, end=49, kind="", source="dictionary")
    assert merge([second, first]) == [first, second]
