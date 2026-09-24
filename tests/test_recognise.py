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


@dataclass(frozen=True)
class TitleArchive:
    """An archive that knows titles only - enough for the dictionary, which reads no content."""

    titles: frozenset[str]

    def has(self, title: str) -> bool:
        return title in self.titles


# "Wassers" is a village and "Wasser" the substance; "Abraham" the patriarch and "Abraham Lincoln" the president
GENITIVE = TitleArchive(
    frozenset(
        {"Kreislauf", "Wasser", "Wassers", "Abraham", "Abraham Lincoln", "Kurs", "Kur", "Reich", "Reiche", "Darau"}
        | {"Goethe", "Faust", "Johann Bereit", "Bereit", "Thales von Milet", "Fall"}
    )
)


def titles_in(text: str) -> dict[str, str | None]:
    """Each mention of the dictionary with the title it names; None where that is the text itself."""
    found = mentions_from_titles([GENITIVE], text)
    assert all(text[mention.start : mention.end] == mention.text for mention in found), "the text stays as written"
    return {mention.text: mention.title for mention in found}


def test_after_a_genitive_article_the_base_form_names_the_article() -> None:
    """M18: "des Wassers" linked the village Wassers, not the water."""
    assert titles_in("Der Kreislauf des Wassers ist ein Thema.") == {"Kreislauf": None, "Wassers": "Wasser"}
    assert titles_in("Die Dichte des kalten Wassers steigt.")["Wassers"] == "Wasser", "one word may stand between"


def test_without_the_article_the_word_itself_wins() -> None:
    assert titles_in("Das Dorf Wassers liegt am Fluss.") == {"Wassers": None}
    assert titles_in("Der Kurs beginnt morgen.") == {"Kurs": None}, "a title keeps its meaning, no Kur"


def test_a_name_in_the_genitive_names_its_article() -> None:
    """M18: "Abraham Lincolns" linked the patriarch Abraham; the longer name without its ending exists."""
    assert titles_in("Abraham Lincolns Rede ist berühmt.") == {"Abraham Lincolns": "Abraham Lincoln"}


def test_the_ending_es_is_tried_before_s() -> None:
    """M18: "des Reiches" named the article Reiche; the genitive of Reich is Reiches."""
    assert titles_in("Die Grenzen des Reiches wuchsen.") == {"Reiches": "Reich"}


def test_a_word_at_the_start_of_a_sentence_is_no_genitive_before_a_small_word() -> None:
    """M18: "Daraus" and "Bereits" open sentences; read as genitives they named a village and a person."""
    assert titles_in("Daraus folgt nichts. Bereits im Mittelalter nicht.") == {}
    assert titles_in("Goethes Faust ist ein Drama.") == {"Goethes": "Goethe", "Faust": None}, "before a noun it is"


def test_an_adverb_in_s_opens_no_term_even_before_a_name() -> None:
    """M18: "Bereits Thales von Milet soll ..." linked the person Johann Bereit through the base form Bereit."""
    assert titles_in("Bereits Thales von Milet soll es entdeckt haben.") == {"Thales von Milet": None}
    assert titles_in("Die Lösung des Falls war einfach.") == {"Falls": "Fall"}, "after an article it is a genitive"
