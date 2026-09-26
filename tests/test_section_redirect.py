"""A redirect to a section of another article leads a topic to that article (M35).

The archives keep such a redirect as a page of its own: a meta refresh to "./Bruchrechnung#Nenner" and the title as
its only text. The topic "Nenner" resolved to that page, sure of it, and the compendium got a main article of six
characters; the gold of the article choice counted "Physik: Leiter" wrong for the same reason, although the service
took "Leiter (Physik)", the article "Elektrischer Leiter" leads to. ``read`` keeps returning the page itself:
Wikidata gives many of these pages an object of their own, and /entities names it (D43).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from libzim.writer import Creator

from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import ZimRegistry
from tests.conftest import HtmlItem

REFRESH = (
    '<html><head><title>{title}</title><meta http-equiv="refresh" content="0;URL=\'./{target}\'" /></head>'
    '<body><a href="./{target}">{title}</a></body></html>'
)
ARTICLES = {
    "Bruchrechnung": "<p>Die Bruchrechnung rechnet mit Brüchen aus Zähler und Nenner.</p>"
    "<h2>Nenner</h2><p>Der Nenner gibt an, in wie viele gleiche Teile das Ganze geteilt ist.</p>",
    "Leiter (Physik)": "<p>Ein Leiter ist in der Physik ein Stoff, der elektrischen Strom oder Wärme gut leitet.</p>",
}
SECTIONS = {
    "Nenner": "Bruchrechnung#Nenner",
    "Elektrischer Leiter": "Leiter_(Physik)#Elektrischer_Leiter",
    "Kreisverweis": "Kreisverweis#Anfang",  # a page that leads to itself ends the way anyway
}


@pytest.fixture(scope="module")
def zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("zim") / "wikipedia_de_abschnitte_2026-01.zim"
    with Creator(str(path)) as creator:
        creator.set_mainpath("Bruchrechnung")
        for title, body in ARTICLES.items():
            html = f"<html><head><title>{title}</title></head><body>{body}</body></html>"
            creator.add_item(HtmlItem(title.replace(" ", "_"), title, html))
        for title, target in SECTIONS.items():
            creator.add_item(HtmlItem(title.replace(" ", "_"), title, REFRESH.format(title=title, target=target)))
    return path


def test_a_topic_that_redirects_to_a_section_resolves_to_its_article(zim: Path) -> None:
    registry = ZimRegistry([zim])
    assert registry.resolve_topic("Nenner").title == "Bruchrechnung"
    leiter = registry.resolve_topic("Elektrischer Leiter", terms=["physik", "strom"])
    assert (leiter.title, leiter.confident) == ("Leiter (Physik)", True)


def test_the_archive_follows_a_section_redirect_only_when_asked(zim: Path) -> None:
    archive = ZimArchive(zim)
    page, article = archive.read("Nenner"), archive.read_article("Nenner")
    assert page is not None and page.title == "Nenner", "the page itself, which Wikidata may know as its own object"
    assert article is not None and article.title == "Bruchrechnung"
    looping = archive.read_article("Kreisverweis")
    assert looping is not None and looping.title == "Kreisverweis"
