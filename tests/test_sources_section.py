"""Sources block of part 1: the licence note without sources names no empty list, and what it says about the rights
follows the licences of the sources (audit 2026-10-02, A09)."""

from app.domain.models import Source
from app.synthesis.sources_section import build_sources_section

OPTIK = Source(
    source_id="wikipedia:Optik", project="wikipedia", title="Optik", url="https://de.wikipedia.org/wiki/Optik"
)


def material(title: str, licence: str) -> Source:
    return Source(
        source_id=f"wlo:{title}",
        project="wlo_material",
        title=title,
        url=f"https://example.org/{title}",
        license=licence,
    )


def test_the_licence_note_without_sources_names_no_empty_list() -> None:
    text = build_sources_section([], [], facets_visible=False)
    assert "()" not in text and "Lizenz- und Attributionshinweis" in text


def test_free_sources_keep_the_free_wording_and_cc_by_sa_for_part_one() -> None:
    sources = [OPTIK, material("Blatt", "CC BY 4.0"), material("Bild", "CC0 1.0"), material("Heft", "CC BY-SA 3.0")]

    text = build_sources_section(sources, [], facets_visible=True)

    assert "aus folgenden freien Wissensbeständen:" in text
    assert text.count("[Zugang: frei]") == 4
    assert text.rstrip().endswith("Teil 1 steht unter CC BY-SA 4.0.")


def test_a_source_without_a_free_licence_is_named_and_part_one_is_not_called_free() -> None:
    # Since D70 a knowledge collection brings materials of any licence; the block still called them all free
    restricted = material("Stationsarbeit", "urheberrechtlich geschützt")

    text = build_sources_section([OPTIK, restricted], [], facets_visible=True)

    assert "freien Wissensbeständen" not in text
    assert "aus folgenden Quellen:" in text
    entry = next(line for line in text.splitlines() if "Stationsarbeit" in line and line.startswith("- **"))
    assert "Zugang" not in entry  # unknown for a material without a free licence
    assert "Teil 1 steht unter CC BY-SA 4.0." not in text
    assert "„Stationsarbeit“ (urheberrechtlich geschützt)" in text
    assert "gelten die Bedingungen der Quelle" in text


def test_a_material_without_a_licence_counts_as_not_free() -> None:
    text = build_sources_section([OPTIK, material("Blatt", "ohne Lizenzangabe")], [], facets_visible=False)

    assert "freien Wissensbeständen" not in text and "„Blatt“ (ohne Lizenzangabe)" in text
