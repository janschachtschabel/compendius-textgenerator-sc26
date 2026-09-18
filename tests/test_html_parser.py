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
