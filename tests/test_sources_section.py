"""Sources block of part 1: the licence note without sources names no empty list, and what it says about the rights
follows the licences of the sources (audit 2026-10-02, A09)."""

import pytest

from app.domain.models import Source
from app.sources.wlo.models import LICENSE_LABELS, license_label
from app.synthesis.sources_section import build_sources_section, freely_accessible

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


def test_access_is_free_for_every_cc_licence_and_a_material_that_says_so() -> None:
    # Jan, 2026-10-03, on the warning of the missing facet: access is not the licence. NC and ND restrict the use of an
    # openly published text, "frei zugänglich" says it outright; in the Optik collection of the staging 12 of 13 materials
    # without a free licence are one of them, the thirteenth names no licence
    sources = [OPTIK, material("Heft", "CC BY-NC-SA 4.0"), material("Seite", "frei zugänglich (keine OER-Lizenz)")]

    text = build_sources_section(sources, [], facets_visible=True)

    assert text.count("[Zugang: frei]") == 3
    assert "„Heft“ (CC BY-NC-SA 4.0) und „Seite“ (frei zugänglich (keine OER-Lizenz)) tragen keine freie Lizenz" in text


@pytest.mark.parametrize(
    ("key", "free"),
    [
        ("CC_0", True),
        ("PDM", True),
        ("CC_BY", True),
        ("CC_BY_NC_ND", True),
        ("COPYRIGHT_FREE", True),
        ("COPYRIGHT_LICENSE", False),
        ("CUSTOM", False),
        ("SCHULFUNK", False),
        ("UNTERRICHTS_UND_LEHRMEDIEN", False),
        ("", False),
    ],
)
def test_the_labels_of_the_repository_say_whether_access_is_free(key: str, free: bool) -> None:
    """The block reads access off the licence label the WLO adapter writes; this pins the two together."""
    assert key in LICENSE_LABELS
    assert freely_accessible(license_label(key, "4.0")) is free
