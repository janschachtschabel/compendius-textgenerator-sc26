"""The DBpedia URI of a German Wikipedia article (D43): built from the title, the way DBpedia forms its IRIs.

Nothing is looked up; the URI is constructed, and the endpoint says so in its schema.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from app.knowledge.identifiers import dbpedia_uri, identifiers
from app.sources.gnd.index import GndIndex, build_gnd_index
from app.sources.wikidata.index import WikidataIndex, build_index
from tests.test_gnd_index import write_dumps as write_gnd_dumps
from tests.test_wikidata_index import write_dumps as write_wikidata_dumps

BASE = "http://de.dbpedia.org/resource/"


def test_the_dbpedia_uri_is_the_title_with_underscores() -> None:
    assert dbpedia_uri("Ernst Abbe") == BASE + "Ernst_Abbe"


def test_umlauts_and_brackets_stay_as_in_the_title() -> None:
    assert dbpedia_uri("Leiter (Physik)") == BASE + "Leiter_(Physik)"
    assert dbpedia_uri("Römisches Reich") == BASE + "Römisches_Reich"


def test_characters_with_a_meaning_in_a_uri_are_escaped() -> None:
    assert dbpedia_uri("Was ist Aufklärung?") == BASE + "Was_ist_Aufklärung%3F"
    assert dbpedia_uri("100 % Wolle") == BASE + "100_%25_Wolle"


LIVE = "http://dbpedia.org/resource/"


def test_with_an_english_article_the_uri_is_the_live_dbpedia_resource() -> None:
    """de.dbpedia.org no longer answers (M42); DBpedia names its live resources after the English article (D65)."""
    assert dbpedia_uri("Römisches Reich", english="Roman Empire") == LIVE + "Roman_Empire"
    assert dbpedia_uri("Was ist Aufklärung?", english="What Is Enlightenment?") == LIVE + "What_Is_Enlightenment%3F"


def test_without_an_english_article_the_german_iri_stays() -> None:
    assert dbpedia_uri("Deutschunterricht", english=None) == BASE + "Deutschunterricht"


def _normdaten(kind: str, gnd: str | None) -> str:
    link = f' <a class="external text" href="https://d-nb.info/gnd/{gnd}">{gnd}</a>' if gnd else ""
    return f'<div id="normdaten"><div>Normdaten&nbsp;({kind}): GND:{link}</div></div>'


@pytest.fixture
def indexes(tmp_path: Path) -> Iterator[tuple[WikidataIndex, GndIndex]]:
    """Zahl is item Q11563 and a GND subject heading; Tetraethylblei has no item, but the GND knows the name."""
    pages = [(10, 0, "Zahl", 0), (11, 0, "Tetraethylblei", 0), (12, 0, "Windelwechsel", 0)]
    props = [(10, "wikibase_item", "Q11563"), (11, "wikibase_item", "Q424242"), (12, "wikibase_item", "Q515151")]
    build_index(*write_wikidata_dumps(tmp_path / "wd", pages=pages, props=props), tmp_path / "wikidata.db")
    build_gnd_index(write_gnd_dumps(tmp_path / "gnd"), tmp_path / "gnd.db")
    with closing(WikidataIndex(tmp_path / "wikidata.db")) as wikidata, closing(GndIndex(tmp_path / "gnd.db")) as gnd:
        yield wikidata, gnd


def test_the_normdaten_block_goes_first_and_says_so(indexes: tuple[WikidataIndex, GndIndex]) -> None:
    found = identifiers("Zahl", _normdaten("Sachbegriff", "4000001-1"), *indexes)
    assert (found.gnd, found.gnd_kind, found.gnd_source) == ("4000001-1", "Sachbegriff", "normdaten")


def test_without_a_normdaten_gnd_the_record_that_names_the_item_is_taken(
    indexes: tuple[WikidataIndex, GndIndex],
) -> None:
    found = identifiers("Zahl", "<p>kein Block</p>", *indexes)
    assert (found.gnd, found.gnd_kind, found.gnd_source) == ("4067271-2", "Sachbegriff", "wikidata")
    assert found.same_as[0] == "https://d-nb.info/gnd/4067271-2"


def test_then_the_one_record_with_the_title_as_its_name(indexes: tuple[WikidataIndex, GndIndex]) -> None:
    found = identifiers("Tetraethylblei", _normdaten("Sachbegriff", None), *indexes)
    assert (found.gnd, found.gnd_source) == ("4145940-4", "name"), "a block without a GND does not stop the lookup"


def test_without_any_hint_there_is_no_gnd(indexes: tuple[WikidataIndex, GndIndex]) -> None:
    found = identifiers("Windelwechsel", "<p>kein Block</p>", *indexes)
    assert (found.gnd, found.gnd_kind, found.gnd_source) == (None, None, None)
    assert identifiers("Zahl", "<p>kein Block</p>", indexes[0]).gnd is None, "without the GND index nothing is filled"


def test_a_record_of_another_kind_than_the_block_names_is_not_the_articles(
    indexes: tuple[WikidataIndex, GndIndex],
) -> None:
    """The block calls the article a person: the subject heading the item or the title leads to is another thing."""
    found = identifiers("Zahl", _normdaten("Person", None), *indexes)
    assert (found.gnd, found.gnd_kind, found.gnd_source) == (None, "Person", None)
