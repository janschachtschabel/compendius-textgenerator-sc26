"""The Normdaten block of a German Wikipedia article: the authority record behind it (docs/entwicklung M18).

The Kiwix dump keeps the block, so the GND number of a linked article needs no download and no network. Only the
block counts: a GND link in the references names an author or a book, not the article.
"""

from __future__ import annotations

from pathlib import Path

from app.sources.zim.normdaten import Normdaten, read_normdaten

FIXTURES = Path(__file__).parent / "fixtures" / "zim_html"


def page(project: str, name: str) -> str:
    return (FIXTURES / project / name).read_text(encoding="utf-8")


def test_a_person_carries_kind_gnd_and_viaf() -> None:
    assert read_normdaten(page("wikipedia", "Ernst_Abbe.html")) == Normdaten(
        kind="Person", gnd="118646419", viaf="19744386"
    )


def test_a_subject_heading_carries_its_gnd_with_the_check_digit() -> None:
    assert read_normdaten(page("wikipedia", "Optik.html")) == Normdaten(kind="Sachbegriff", gnd="4043650-0", viaf=None)


def test_an_article_without_the_block_has_no_normdaten() -> None:
    assert read_normdaten(page("klexikon", "Optik.html")) is None


def test_a_gnd_link_outside_the_block_does_not_count() -> None:
    reference = '<p>Literatur: <a href="https://d-nb.info/gnd/118540238">Goethe</a></p>'
    block = (
        '<div id="normdaten"><div>Normdaten&nbsp;(Sachbegriff): <a href="Gemeinsame_Normdatei">GND</a>: '
        '<a href="https://d-nb.info/gnd/4043650-0">4043650-0</a></div></div>'
    )
    assert read_normdaten(reference) is None
    assert read_normdaten(reference + block) == Normdaten(kind="Sachbegriff", gnd="4043650-0", viaf=None)


def test_a_gnd_link_after_the_block_does_not_count() -> None:
    block = '<div id="normdaten"><div>Normdaten&nbsp;(Person): <a href="https://id.loc.gov/authorities/n1">n1</a></div></div>'
    after = '<p>Literatur: <a href="https://d-nb.info/gnd/118540238">Goethe</a></p>'
    assert read_normdaten(block + after) == Normdaten(kind="Person", gnd=None, viaf=None)


def test_a_block_without_a_gnd_number_keeps_its_kind() -> None:
    block = '<div id="normdaten">Normdaten&nbsp;(Person): <a href="https://id.loc.gov/authorities/n1">n1</a></div>'
    assert read_normdaten(block) == Normdaten(kind="Person", gnd=None, viaf=None)


def test_a_gnd_number_ending_in_x_is_read_whole() -> None:
    block = '<div id="normdaten">Normdaten (Person): <a href="https://d-nb.info/gnd/10054753X">10054753X</a></div>'
    assert read_normdaten(block) == Normdaten(kind="Person", gnd="10054753X", viaf=None)
