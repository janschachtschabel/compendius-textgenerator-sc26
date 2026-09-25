"""When the subject overrides an exact title with a meaning of its disambiguation page (M9, M25).

"Informatik: Baum" took the plant, whose opening names nothing of computing; the meaning "Baum (Datenstruktur)" of
"Baum (Begriffsklärung)" carries the subject in its title and wins. M25 found the same rule turning "Kreis" with the
subject Mathematik into "Soziale Gruppe": the geometry article opens without the word Mathematik, and the social
group mentions "mathematisch" once in its text. A meaning overrides an exact title only when its title names the
subject - the place where a German disambiguation page keeps the distinction.
"""

from __future__ import annotations

import pytest
from libzim.writer import Creator

from app.sources.zim.registry import ZimRegistry
from tests.conftest import HtmlItem

LIST = "<ul>{items}</ul><p>Dies ist eine Begriffsklärungsseite zur Unterscheidung mehrerer Begriffe.</p>"
ARTICLES = {
    "Kreis": "<p>Ein Kreis ist eine ebene geometrische Figur aus allen Punkten gleichen Abstands.</p>",
    "Kreis (Begriffsklärung)": LIST.format(
        items='<li><a href="Kreis" title="Kreis">Kreis</a>, geometrische Figur</li>'
        '<li><a href="Soziale_Gruppe" title="Soziale Gruppe">Soziale Gruppe</a>, Menschen</li>'
    ),
    "Soziale Gruppe": "<p>Eine soziale Gruppe besteht aus Menschen; die mathematische Soziologie zählt sie.</p>",
    "Baum": "<p>Ein Baum ist eine verholzte Pflanze mit Stamm, Ästen und Krone.</p>",
    "Baum (Begriffsklärung)": LIST.format(
        items='<li><a href="Baum" title="Baum">Baum</a>, Pflanze</li>'
        '<li><a href="Baum_(Datenstruktur)" title="Baum (Datenstruktur)">Baum (Datenstruktur)</a>, Struktur</li>'
    ),
    "Baum (Datenstruktur)": "<p>Ein Baum verbindet Knoten ohne Kreise.</p>",
}


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> ZimRegistry:
    path = tmp_path_factory.mktemp("zim") / "wikipedia_de_bedeutungen_2026-01.zim"
    with Creator(str(path)) as creator:
        creator.set_mainpath("Kreis")
        for title, body in ARTICLES.items():
            html = f"<html><head><title>{title}</title></head><body>{body}</body></html>"
            creator.add_item(HtmlItem(title.replace(" ", "_"), title, html))
    return ZimRegistry([path])


def test_a_meaning_that_names_the_subject_in_its_title_overrides_the_exact_title(registry: ZimRegistry) -> None:
    resolution = registry.resolve_topic("Baum", terms=["informatik", "daten"])
    assert resolution.title == "Baum (Datenstruktur)" and resolution.method == "disambiguation"


def test_a_meaning_that_names_the_subject_only_in_its_text_does_not(registry: ZimRegistry) -> None:
    resolution = registry.resolve_topic("Kreis", terms=["mathematik", "mathematisch"])
    assert resolution.title == "Kreis" and resolution.method == "title"
    assert not resolution.confident, "the exact title still says nothing of the subject: a guess"
