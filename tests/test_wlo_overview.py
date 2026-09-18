"""Part 3 rendering: purpose, key figures, compact material lists, sub-collections, parseable blocks."""

import json
import re
from dataclasses import replace
from pathlib import Path

from app.sources.wlo.models import parse_collection, parse_reference, parse_subcollection
from app.sources.wlo.overview import OverviewOptions, SubCollectionContents, render_collection_overview

FIX = Path(__file__).parent / "fixtures" / "wlo"


def _load(name: str) -> dict:  # type: ignore[type-arg]
    data: dict = json.loads((FIX / name).read_text(encoding="utf-8"))  # type: ignore[type-arg]
    return data


INFO = parse_collection(_load("collection_optik.json"))
REFS = [
    parse_reference(n)
    for page in ("references_optik_page1.json", "references_optik_page2.json")
    for n in _load(page)["references"]
]
SUBS = [parse_subcollection(n) for n in _load("subcollections_optik.json")["collections"]]


def _render_url(node_id: str) -> str:
    return f"https://repo.test/edu-sharing/components/render/{node_id}"


def test_overview_has_purpose_key_figures_materials_and_subcollections_in_parseable_blocks() -> None:
    subs = [SubCollectionContents(info=sub, refs=tuple(REFS[:2]) if i == 0 else ()) for i, sub in enumerate(SUBS)]
    text, summary = render_collection_overview(INFO, REFS, subs, render_url=_render_url, options=OverviewOptions())

    assert text.startswith("## Teil 3 · Die Sammlung im Überblick")
    assert "Die Physik des Lichts" in text
    assert "16 Inhalte" in text and "4 Untersammlungen" in text
    assert "Physik (16)" in text and "CC BY-SA 4.0 (3)" in text and "CC0 1.0 (3)" in text
    assert "### Inhalte der Sammlung" in text and "### Untersammlungen" in text
    assert "#### Geometrische Optik" in text and "#### Menschliches Auge" in text
    assert "- **Optik** · Faszinierende Phänomene aus der Optik · Schlagwörter: Optik, Phänomene, Spiegel" in text
    assert "CC BY-NC-SA 4.0 · [Material](https://www.geogebra.org/m/PzBHcpNG)" in text
    assert (
        "[Sammlung öffnen](https://repo.test/edu-sharing/components/render/9e7ae956-e9df-430f-bace-f3db4b910013)"
        in text
    )
    blocks = re.findall(r"<!-- f: (.*?) -->\n(.*?)<!-- /f -->", text, re.S)
    assert len(blocks) == 1 + 1 + 4  # head, own materials, four sub-collections
    facets = dict(pair.split("=", 1) for pair in blocks[0][0].split("; "))
    assert facets["Sammlung"] == INFO.id and facets["Fach"] == "Physik" and facets["Bildungsstufe"] == "Sek I"
    sub_facets = dict(pair.split("=", 1) for pair in blocks[2][0].split("; "))
    assert sub_facets["Sammlung"] == SUBS[0].id and sub_facets["Übergeordnet"] == INFO.id
    assert "weitere" not in text
    assert summary["materials"] == 16 and summary["subcollections"] == 4
    assert summary["licenses"]["CC BY-SA 4.0"] == 3 and summary["subjects"]["Physik"] == 16  # plus four minor subjects
    assert summary["subcollection_materials"]["Geometrische Optik"] == 2


def test_missing_descriptions_are_named_and_a_cap_is_honest() -> None:
    bare = replace(INFO, description="")
    refs = [replace(ref, description="") for ref in REFS]
    text, summary = render_collection_overview(
        bare, refs, [], render_url=_render_url, options=OverviewOptions(max_items=5)
    )
    assert "keine Beschreibung hinterlegt" in text
    assert text.count("- **") == 5 and "*weitere 11 Inhalte*" in text
    assert summary["missing_descriptions"] == 16
    assert "### Untersammlungen" not in text
