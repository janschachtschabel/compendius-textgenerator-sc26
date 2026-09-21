from pathlib import Path

from app.sources.zim.html import parse_article
from tests.conftest import FIXTURES


def _read(project: str, name: str) -> str:
    return (FIXTURES / project / name).read_text(encoding="utf-8")


def test_lead_and_sections_of_optik(optik_html: str) -> None:
    parsed = parse_article(optik_html, "Optik")
    lead = parsed.sections[0]
    assert lead.level == 0
    assert lead.paragraphs[0].text.startswith("Die Optik")
    text = parsed.text
    assert "[1]" not in text, "footnote markers must be stripped"
    assert "mw-parser-output" not in text, "inline style blocks must be stripped"
    headings = [s.heading for s in parsed.sections]
    assert "Teilbereiche der Optik" in headings
    geometric = next(s for s in parsed.sections if s.heading == "Geometrische Optik")
    assert geometric.path == ["Teilbereiche der Optik", "Geometrische Optik"]
    assert geometric.level == 3


def test_links_and_aliases(optik_html: str) -> None:
    parsed = parse_article(optik_html, "Optik")
    assert "Geometrische Optik" in parsed.links
    assert "Wellenoptik" in parsed.links
    assert not any(link.startswith(("Datei:", "Kategorie:")) for link in parsed.links)
    assert "Lehre vom Licht" in parsed.aliases


def test_disambiguation_is_detected() -> None:
    parsed = parse_article(_read("wikipedia", "Optik_(Begriffskl_rung).html"), "Optik (Begriffsklärung)")
    assert parsed.is_disambiguation
    assert "Optik" in parsed.links


def test_klexikon_lead_without_thumbnail_noise() -> None:
    parsed = parse_article(_read("klexikon", "Optik.html"), "Optik")
    lead = parsed.sections[0].paragraphs[0].text
    assert lead.startswith("Die Optik ist die Lehre vom Licht.")
    assert "Datei:" not in parsed.text


def test_person_lead_keeps_birth_data() -> None:
    parsed = parse_article(_read("wikipedia", "Ernst_Abbe.html"), "Ernst Abbe")
    lead = parsed.sections[0].paragraphs[0].text
    assert "(* 23. Januar 1840" in lead
    assert "/* start" not in lead


def test_lists_become_list_paragraphs(optik_html: str) -> None:
    parsed = parse_article(optik_html, "Optik")
    kinds = {p.kind.value for s in parsed.sections for p in s.paragraphs}
    assert "list" in kinds


def test_all_fixtures_parse() -> None:
    for path in FIXTURES.rglob("*.html"):
        parsed = parse_article(Path(path).read_text(encoding="utf-8"), path.stem)
        assert parsed.sections, path


def test_a_long_disambiguation_page_is_detected_although_its_note_stands_at_the_end() -> None:
    """Measured against the real Wikipedia on 2026-09-20: the note sits at character 2254 of 2562 in
    "Schöpfer" and at 5815 of 6124 in "Feld". A window over the beginning does not reach it, and both pages
    came back as articles - "Schöpfer" as a person, "Feld" as a piece of farmland."""
    entries = "".join(f"<p>Bedeutung {index}: eine von vielen Lesarten dieses Wortes.</p>" for index in range(40))
    html = (
        "<html><body><p>Schöpfer steht für:</p>"
        + entries
        + "<p>Dies ist eine Begriffsklärungsseite zur Unterscheidung mehrerer mit demselben Wort "
        "bezeichneter Begriffe.</p></body></html>"
    )
    parsed = parse_article(html, "Schöpfer")
    assert parsed.text.lower().index("begriffsklärungsseite") > 2000, "otherwise the old window would reach it"
    assert parsed.is_disambiguation


def test_an_article_that_never_mentions_the_note_stays_an_article(optik_html: str) -> None:
    """The counter-check to the open window: measured on 600 random articles, none of them flipped."""
    assert not parse_article(optik_html, "Optik").is_disambiguation


def test_a_link_inside_a_list_is_marked_as_one() -> None:
    """Which links a disambiguation page offers as meanings is a question of where they stand.

    Measured against the real Wikipedia on 2026-09-21: deciding it by searching the list *text* threw away
    19 real meanings to remove 3 etymology links, because the rendered label of a link is not its title
    ("Bezirk Friedrichshain-Kreuzberg", "Punktierung (Musik)"). The parser knows the difference.
    """
    html = (
        "<html><body><p>Punkt (<a href='Latein' title='Latein'>lateinisch</a> punctum) steht für:</p>"
        "<ul><li><a href='Punkt_(Geometrie)' title='Punkt (Geometrie)'>Punkt</a> in der Geometrie</li>"
        "<li><a href='Punktewertung' title='Punktewertung'>Punktewertung</a> im Sport</li></ul>"
        "</body></html>"
    )
    parsed = parse_article(html, "Punkt")
    assert parsed.links == ["Latein", "Punkt (Geometrie)", "Punktewertung"]
    assert parsed.list_links == ["Punkt (Geometrie)", "Punktewertung"]
