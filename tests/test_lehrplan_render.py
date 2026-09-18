"""Part 2 rendering: coverage note, state x level table, grouped entries with markers, budget, hint texts."""

import json
import re

from app.sources.lehrplan.matcher import CurriculumMatch, MatchResult
from app.sources.lehrplan.render import RenderOptions, render_curricula, render_missing_cache
from app.sources.lehrplan.store import LehrplanRecord, NodeHit
from app.sources.lehrplan.stufen import resolve_klassenstufe, resolve_schulstufe

META = {"harvested_at": "2026-09-17T12:00:00+00:00", "counts": json.dumps({"BY": 1707, "SN": 532, "RP": 229, "BE": 46})}
SN = LehrplanRecord(
    iri="https://lp-sachsen.org/resource/522",
    label="Gymnasium Physik",
    bundesland_code="SN",
    bundesland="Sachsen",
    schularten=["Gymnasium"],
    schulfaecher=["Physik"],
    schulstufen=["Sekundarbereich I"],
)
RP = LehrplanRecord(
    iri="https://lp-rlp.org/resource/lehrplan-7",
    label="Physik, Grund- und Leistungsfach in der gymnasialen Oberstufe",
    bundesland_code="RP",
    bundesland="Rheinland-Pfalz",
    schulfaecher=["Physik"],
)
BY = LehrplanRecord(
    iri="https://lp-bavaria.org/nt5",
    label="Natur und Technik 5",
    bundesland_code="BY",
    bundesland="Bayern",
    schularten=["Gymnasium"],
    schulfaecher=["Natur und Technik"],
    jahrgangsstufen=["Jahrgangsstufe 5"],
)


def _match(
    iri: str, label: str, rollen: list[str], lehrplan: LehrplanRecord, parent: str = "", grades: list[str] | None = None
) -> CurriculumMatch:
    hit = NodeHit(
        iri=iri,
        label=label,
        rollen=rollen,
        parent_iri=None,
        parent_label=parent,
        jahrgangsstufen=grades or [],
        depth=1,
        lehrplan=lehrplan,
        matched_in="label",
    )
    return CurriculumMatch(
        hit=hit,
        keyword="Optik",
        schulstufe=resolve_schulstufe(hit.jahrgangsstufen, lehrplan),
        klassenstufe=resolve_klassenstufe(hit.jahrgangsstufen, lehrplan),
        score=0,
    )


def _result(*matches: CurriculumMatch) -> MatchResult:
    return MatchResult(
        keywords=["Optik", "Licht"],
        subject_terms=["physik"],
        matches=list(matches),
        total_hits=len(matches) + 1,
        excluded_noise=1,
    )


def test_render_groups_matches_by_level_state_and_curriculum_with_markers() -> None:
    result = _result(
        _match("sn:lb", "Lernbereich 2: Optik", ["themenbereich"], SN, "Gymnasium Physik", ["Klassenstufe 7"]),
        _match(
            "sn:k1", "Lichtbrechung an Linsen", ["kompetenz", "inhalt"], SN, "Lernbereich 2: Optik", ["Klassenstufe 7"]
        ),
        _match("rp:k", "Licht als Welle und Teilchen verstehen", ["kompetenz"], RP, "Lernbereich 7"),
        _match("by:i", "Schatten und Finsternisse", ["inhalt"], BY, "Optik: Sehen und gesehen werden"),
    )
    text, summary = render_curricula(result, meta=META, options=RenderOptions())

    assert text.startswith("## Teil 2 · Lehrplanbezüge")
    assert "Bayern, Sachsen, Rheinland-Pfalz und Berlin" in text and "Stand 2026-09-17" in text
    assert "| Bundesland | Primarstufe | Sekundarstufe I | Sekundarstufe II |" in text
    assert "| Sachsen | 0 | 2 | 0 |" in text and "| Rheinland-Pfalz | 0 | 0 | 1 |" in text
    assert (
        text.index("### Sekundarstufe I")
        < text.index("#### Bayern")
        < text.index("#### Sachsen")
        < text.index("### Sekundarstufe II")
    )
    assert "*LehrplanPLUS: Natur und Technik 5*" in text and "*Lehrplan: Gymnasium Physik*" in text
    marker = "<!-- f: Bundesland=Sachsen; Bildungsstufe=Sek I; Klassenstufe=7; Schulart=Gymnasium; Lehrplan=https://lp-sachsen.org/resource/522 -->"
    assert marker in text
    assert "„Lichtbrechung an Linsen“ (Kompetenz, Inhalt) · [Lehrplanelement](sn:k1)" in text
    assert "**Lernbereich 2: Optik**" in text  # the Bereich heads its group and is not repeated as an entry
    assert "*(abgeleitet aus Lehrplantitel)*" in text  # RP level comes from the title, not the data
    assert "[Bildungsstufe:" not in text
    assert summary["matches"] == 4 and summary["lehrplaene"] == 3 and summary["laender"] == 3
    assert summary["by_land"]["Sachsen"] == {"Sekundarstufe I": 2}
    assert summary["datenlage"]["stufe"]["Daten (Lehrplan)"] == 2
    assert summary["excluded_noise"] == 1 and summary["keywords"] == ["Optik", "Licht"]


def test_visible_facets_and_budget_per_state() -> None:
    matches = [
        _match(f"sn:{i}", f"Kompetenz {i}", ["kompetenz"], SN, f"Lernbereich {i}", ["Klassenstufe 7"]) for i in range(5)
    ]
    text, _summary = render_curricula(
        _result(*matches), meta=META, options=RenderOptions(max_groups_per_land=2, facets_visible=True)
    )
    assert "[Bildungsstufe: Sek I] [Geltungsebene: Land]" in text
    assert text.count("**Lernbereich ") == 2
    assert "weitere 3 Einträge" in text


def test_empty_result_and_missing_cache_are_honest_texts() -> None:
    text, summary = render_curricula(_result(), meta=META, options=RenderOptions())
    assert "keine Lehrplanbezüge gefunden" in text and "Bayern, Sachsen" in text
    assert summary["matches"] == 0 and "<!-- f:" not in text
    hint = render_missing_cache()
    assert hint.startswith("## Teil 2 · Lehrplanbezüge") and "Lehrplan-Cache" in hint and "<!-- f:" not in hint


def test_default_renders_every_group_and_item_between_parseable_markers() -> None:
    """Compendia may be long: nothing is cut unless a cap is configured, and every block can be parsed out."""
    matches = [
        _match(f"sn:{i}", f"Kompetenz {i}", ["kompetenz"], SN, f"Lernbereich {i % 6}", ["Klassenstufe 7"])
        for i in range(30)
    ]
    text, summary = render_curricula(_result(*matches), meta=META, options=RenderOptions())
    assert text.count("**Lernbereich ") == 6 and "nicht aufgeführt" not in text and "weitere" not in text
    assert text.count("„Kompetenz ") == 30
    blocks = re.findall(r"<!-- f: (.*?) -->\n(.*?)<!-- /f -->", text, re.S)
    assert len(blocks) == 6 == text.count("<!-- /f -->")
    facets = dict(pair.split("=", 1) for pair in blocks[0][0].split("; "))
    assert facets["Bundesland"] == "Sachsen" and facets["Lehrplan"] == SN.iri
    assert facets["Bildungsstufe"] == "Sek I" and facets["Klassenstufe"] == "7" and facets["Schulart"] == "Gymnasium"
    assert "[Lehrplanelement](sn:" in blocks[0][1]
    assert summary["matches"] == 30
