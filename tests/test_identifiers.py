"""The DBpedia URI of a German Wikipedia article (D43): built from the title, the way DBpedia forms its IRIs.

Nothing is looked up; the URI is constructed, and the endpoint says so in its schema.
"""

from __future__ import annotations

from app.knowledge.identifiers import dbpedia_uri

BASE = "http://de.dbpedia.org/resource/"


def test_the_dbpedia_uri_is_the_title_with_underscores() -> None:
    assert dbpedia_uri("Ernst Abbe") == BASE + "Ernst_Abbe"


def test_umlauts_and_brackets_stay_as_in_the_title() -> None:
    assert dbpedia_uri("Leiter (Physik)") == BASE + "Leiter_(Physik)"
    assert dbpedia_uri("Römisches Reich") == BASE + "Römisches_Reich"


def test_characters_with_a_meaning_in_a_uri_are_escaped() -> None:
    assert dbpedia_uri("Was ist Aufklärung?") == BASE + "Was_ist_Aufklärung%3F"
    assert dbpedia_uri("100 % Wolle") == BASE + "100_%25_Wolle"
