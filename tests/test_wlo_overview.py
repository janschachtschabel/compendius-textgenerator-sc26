"""Part 3 rendering: purpose, key figures, compact material lists, sub-collections, parseable blocks."""

import json
import re
from dataclasses import replace
from pathlib import Path

from app.sources.wlo.models import parse_collection, parse_reference, parse_subcollection
from app.sources.wlo.overview import (
    OverviewOptions,
    SubCollectionContents,
    render_collection_overview,
)

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
# the first sub-collection lists materials, the rest stay empty: both shapes in one render
SUBS_WITH_REFS = [SubCollectionContents(info=s, refs=tuple(REFS[:2]) if i == 0 else ()) for i, s in enumerate(SUBS)]


class _Urls:
    """Stands in for the edu-sharing client: the renderer only needs its two URL builders."""

    def render_url(self, node_id: str) -> str:
        return f"https://repo.test/edu-sharing/components/render/{node_id}"

    def preview_url(self, node_id: str) -> str:
        return f"https://repo.test/edu-sharing/preview?nodeId={node_id}"


URLS = _Urls()


def test_overview_has_purpose_key_figures_materials_and_subcollections_in_parseable_blocks() -> None:
    subs = [SubCollectionContents(info=sub, refs=tuple(REFS[:2]) if i == 0 else ()) for i, sub in enumerate(SUBS)]
    text, summary = render_collection_overview(INFO, REFS, subs, urls=URLS, options=OverviewOptions())

    assert text.startswith("## Teil 3 · Die Sammlung im Überblick")
    assert "Die Physik des Lichts" in text
    assert "16 Inhalte" in text and "4 Untersammlungen" in text
    assert "Physik (16)" in text and "CC BY-SA 4.0 (3)" in text and "CC0 1.0 (3)" in text
    assert "### Inhalte der Sammlung" in text and "### Untersammlungen" in text
    assert "#### Geometrische Optik" in text and "#### Menschliches Auge" in text
    assert "Faszinierende Phänomene aus der Optik · Schlagwörter: Optik, Phänomene, Spiegel" in text
    assert (  # version from the repository, deed linked
        "[**Optik**](https://www.geogebra.org/m/PzBHcpNG) — Lizenz: "
        "[CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/deed.de)"
    ) in text
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
    text, summary = render_collection_overview(bare, refs, [], urls=URLS, options=OverviewOptions(max_items=5))
    assert "keine Beschreibung hinterlegt" in text
    assert text.count("::: wlo-material") == 5 and "*weitere 11 Inhalte*" in text
    assert summary["missing_descriptions"] == 16
    assert "### Untersammlungen" not in text


def test_every_material_is_a_parseable_block_carrying_its_node_id() -> None:
    text, _ = render_collection_overview(INFO, REFS[:1], [], urls=URLS, options=OverviewOptions())

    block = re.search(r"::: wlo-material\n(.*?)\n:::", text, re.S)
    assert block is not None
    lines = [line for line in block.group(1).split("\n") if line]
    assert lines[0] == "![Optik](https://repo.test/edu-sharing/preview?nodeId=4bfa7693-0764-4dca-9720-c5fb0b8892d6)"
    assert lines[1].startswith("[**Optik**](https://www.geogebra.org/m/PzBHcpNG) — Lizenz: ")
    assert lines[2].startswith("Faszinierende Phänomene aus der Optik · Schlagwörter: ")
    assert "Fachliche News" in lines[2] and "Sekundarstufe I" in lines[2]


def test_a_material_without_its_own_url_links_to_its_page_in_the_repository() -> None:
    ref = replace(REFS[0], url="")
    text, _ = render_collection_overview(INFO, [ref], [], urls=URLS, options=OverviewOptions())
    assert f"[**Optik**](https://repo.test/edu-sharing/components/render/{ref.node_id}) — Lizenz: " in text


def test_a_licence_without_a_deed_stays_unlinked_text() -> None:
    ref = replace(REFS[0], license_key="COPYRIGHT_FREE", license_version="")
    text, _ = render_collection_overview(INFO, [ref], [], urls=URLS, options=OverviewOptions())
    assert "— Lizenz: frei zugänglich (keine OER-Lizenz)\n" in text
    assert "creativecommons.org" not in text


def test_brackets_in_a_title_cannot_break_the_block_structure() -> None:
    """Titles come from the repository, so they are untrusted input for the markdown the compendium publishes."""
    ref = replace(REFS[0], title="Arbeitsblatt [PDF] (Teil 1)", url="https://host.test/a b(c).pdf")
    text, _ = render_collection_overview(INFO, [ref], [], urls=URLS, options=OverviewOptions())
    assert r"[**Arbeitsblatt \[PDF\] (Teil 1)**](<https://host.test/a b(c).pdf>)" in text
    assert r"![Arbeitsblatt \[PDF\] (Teil 1)](" in text


def test_blocks_are_separated_by_a_blank_line_so_a_fence_parser_cannot_run_them_together() -> None:
    text, _ = render_collection_overview(INFO, REFS[:3], [], urls=URLS, options=OverviewOptions())
    assert ":::\n::: wlo-material" not in text
    assert text.count(":::\n\n::: wlo-material") == 2
    assert "-->\n\n::: wlo-material" in text  # the facet marker does not touch the first fence
    full, _ = render_collection_overview(INFO, REFS, SUBS_WITH_REFS, urls=URLS, options=OverviewOptions())
    assert "\n\n\n" not in full  # no stray blank runs anywhere in the part


def test_an_empty_collection_says_so_without_an_empty_block() -> None:
    text, _ = render_collection_overview(INFO, [], [], urls=URLS, options=OverviewOptions())
    assert "*Keine Inhalte gelistet.*" in text and "::: wlo-material" not in text


def test_no_repository_field_can_close_the_fence_early() -> None:
    """The fence must survive whatever a contributor typed: angle brackets in a URL, and a keyword that
    carries a line break and a closing fence. Both would otherwise end the block inside a material."""
    ref = replace(
        REFS[0],
        url="https://host.test/a<b>c",
        keywords=("harmlos", "boese" + chr(10) + ":::" + chr(10) + "Text"),
    )
    text, _ = render_collection_overview(INFO, [ref], [], urls=URLS, options=OverviewOptions())

    closings = [line for line in text.split(chr(10)) if line == ":::"]
    assert len(closings) == 1  # exactly one closing fence: nothing in the material closed the block early
    assert "<https://host.test/a%3Cb%3Ec>" in text
    assert text.count("::: wlo-material") == 1
