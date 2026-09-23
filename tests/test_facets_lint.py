from app.domain.models import Chunk, Section, SectionStatus, Source, SourceRole
from app.synthesis.facets import FacetCatalog, annotate, bildungsstufe_facet, format_marker
from app.synthesis.lint import lint_sections
from app.templates.manager import TemplateManager
from tests.conftest import ROOT


def _catalog() -> FacetCatalog:
    return FacetCatalog.load(ROOT / "config" / "facets.yaml")


def _chunk(cid: str, source_id: str, heading: str, text: str) -> Chunk:
    return Chunk(chunk_id=cid, source_id=source_id, heading=heading, heading_path=[heading], heading_level=2, text=text)


def test_zeitbezug_historisch_from_years_and_markers() -> None:
    template = TemplateManager().get("sc26")
    slot = template.slot_by_key("entwicklung_ausblick")
    assert slot is not None
    chunks = [
        _chunk(
            "c1",
            "wikipedia:X",
            "Geschichte",
            "Im Jahr 1604 beschrieb Kepler die Brechung; 1621 fand Snellius das Gesetz, später entdeckte Newton die Dispersion.",
        )
    ]
    sources = {
        "wikipedia:X": Source(
            source_id="wikipedia:X", project="wikipedia", role=SourceRole.LEITQUELLE, title="X", url="u"
        )
    }
    facets = annotate(slot, chunks, sources, _catalog(), level="minimal")
    assert facets["Zeitbezug"] == ["historisch"]
    assert facets["Evidenzgrad"] == ["belegt"]
    assert "Haltbarkeit" not in facets, "minimal level must not annotate Haltbarkeit"


def test_bildungsstufe_from_source_role_and_text() -> None:
    template = TemplateManager().get("sc26")
    slot = template.slot_by_key("bildung")
    assert slot is not None
    chunks = [_chunk("c1", "klexikon:Licht", "Licht", "Kinder lernen in der Grundschule, wie Licht sich ausbreitet.")]
    sources = {
        "klexikon:Licht": Source(
            source_id="klexikon:Licht", project="klexikon", role=SourceRole.EINFACHE_SPRACHE, title="Licht", url="u"
        )
    }
    facets = annotate(slot, chunks, sources, _catalog(), level="full")
    assert "Primar" in facets["Bildungsstufe"]


def test_lint_reports_missing_required_facet() -> None:
    template = TemplateManager().get("sc26")
    sections = [
        Section(
            slot_id="sc26_5",
            slot_key="entwicklung_ausblick",
            title="5",
            text="Text [1]",
            status=SectionStatus.EXTRACTIVE,
            facets={},
        ),
        Section(
            slot_id="sc26_9",
            slot_key="regularien",
            title="9",
            text="Text [2]",
            status=SectionStatus.EXTRACTIVE,
            facets={"Geltungsebene": ["Bund"]},
        ),
    ]
    findings = lint_sections(template, sections, _catalog())
    rules = {(f.rule, f.section_id) for f in findings}
    assert ("facet-required", "sc26_5") in rules
    assert ("facet-required", "sc26_9") not in rules


def test_lint_ignores_empty_sections() -> None:
    template = TemplateManager().get("sc26")
    sections = [
        Section(slot_id="sc26_5", slot_key="entwicklung_ausblick", title="5", text="", status=SectionStatus.EMPTY)
    ]
    assert lint_sections(template, sections, _catalog()) == []


def test_a_level_arrives_as_a_label_or_as_a_vocabulary_uri() -> None:
    """The OpenEduHub vocabulary names a level three ways; all three have to land on the facet value.

    prefLabel ("Sekundarstufe I"), altLabel ("Sekundarstufe 1") and the concept URI
    (.../educationalContext/sekundarstufe_1) are the same level. The labels were already read; the URI
    was not, because its underscore is no whitespace.
    """
    base = "http://w3id.org/openeduhub/vocabs/educationalContext/"
    assert bildungsstufe_facet("Sekundarstufe I") == "Sek I"
    assert bildungsstufe_facet("Sekundarstufe 1") == "Sek I"
    assert bildungsstufe_facet(base + "sekundarstufe_1") == "Sek I"
    assert bildungsstufe_facet(base + "sekundarstufe_2") == "Sek II"
    assert bildungsstufe_facet(base + "elementarbereich") == "Elementar"
    assert bildungsstufe_facet(base + "berufliche_bildung") == "Berufliche Bildung"
    assert bildungsstufe_facet("Sek I") == "Sek I", "the project's own value still maps to itself"
    assert bildungsstufe_facet(base + "informelles_lernen") is None, "no counterpart, and no invented one"


def test_a_marker_stays_on_one_line_whatever_a_value_holds() -> None:
    """Marker values come from sources editors type into - a subject label, a curriculum name. A line break in one
    would end the marker early and put the rest of the value on a line of the document."""
    value = "Physik" + chr(10) + "- Inhalt: x" + chr(0x2028) + "y  "
    assert format_marker({"Fach": [value, "Optik"], "Leer": []}) == "Fach=Physik - Inhalt: x y|Optik"


def test_a_marker_value_cannot_add_a_pair_split_itself_or_end_the_comment() -> None:
    """``;``, ``=`` and ``|`` are the marker's own separators and ``<!--``/``-->`` the ends of the HTML comment it
    stands in; inside a value they are percent-encoded."""
    assert format_marker({"Fach": ["a; b=c|d <!-- e -->"]}) == "Fach=a%3B b%3Dc%7Cd %3C!-- e --%3E"
