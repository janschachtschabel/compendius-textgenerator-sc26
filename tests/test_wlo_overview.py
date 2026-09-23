"""Part 3 rendering: purpose, key figures, parseable material blocks, sub-collections."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from app.sources.wlo.client import validate_node_id
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


def _render_url(node_id: str) -> str:
    return f"https://repo.test/edu-sharing/components/render/{node_id}"


def _checked_render_url(node_id: str) -> str:
    """What the client does: refuse an id the repository could not resolve."""
    return f"https://repo.test/edu-sharing/components/render/{validate_node_id(node_id)}"


def test_overview_has_purpose_key_figures_materials_and_subcollections_in_parseable_blocks() -> None:
    subs = [SubCollectionContents(info=sub, refs=tuple(REFS[:2]) if i == 0 else ()) for i, sub in enumerate(SUBS)]
    text, summary = render_collection_overview(INFO, REFS, subs, render_url=_render_url, options=OverviewOptions())

    assert text.startswith("## Teil 3 · Die Sammlung im Überblick")
    assert "Die Physik des Lichts" in text
    assert "16 Inhalte" in text and "4 Untersammlungen" in text
    assert "Physik (16)" in text and "CC BY-SA 4.0 (3)" in text and "CC0 1.0 (3)" in text
    assert "### Inhalte der Sammlung" in text and "### Untersammlungen" in text
    assert "#### Geometrische Optik" in text and "#### Menschliches Auge" in text
    assert "Faszinierende Phänomene aus der Optik · Schlagwörter: Optik, Phänomene, Spiegel" in text
    # version from the repository, licence as the short label without a link
    assert "[**Optik**](https://www.geogebra.org/m/PzBHcpNG) — Lizenz: CC BY-NC-SA 3.0" in text
    assert "creativecommons.org" not in text
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
    assert text.count("::: wlo-material") == 5 and "*weitere 11 Inhalte*" in text
    assert summary["missing_descriptions"] == 16
    assert "### Untersammlungen" not in text


def test_every_material_is_a_parseable_block_carrying_its_node_id() -> None:
    text, _ = render_collection_overview(INFO, REFS[:1], [], render_url=_render_url, options=OverviewOptions())

    block = re.search(r"::: wlo-material\n(.*?)\n:::", text, re.S)
    assert block is not None
    lines = [line for line in block.group(1).split("\n") if line]
    assert lines[0] == "nodeId: 4bfa7693-0764-4dca-9720-c5fb0b8892d6"
    assert lines[1] == "[**Optik**](https://www.geogebra.org/m/PzBHcpNG) — Lizenz: CC BY-NC-SA 3.0"
    assert lines[2].startswith("Faszinierende Phänomene aus der Optik · Schlagwörter: ")
    assert "Fachliche News" in lines[2] and "Sekundarstufe I" in lines[2]
    assert "![" not in text  # no preview images: the node id points at the material instead


def test_a_material_without_its_own_url_links_to_its_page_in_the_repository() -> None:
    ref = replace(REFS[0], url="")
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_checked_render_url, options=OverviewOptions())
    assert f"[**Optik**](https://repo.test/edu-sharing/components/render/{ref.node_id}) — Lizenz: " in text


def test_the_licence_is_the_short_label_without_a_link() -> None:
    ref = replace(REFS[0], license_key="COPYRIGHT_FREE", license_version="")
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())
    assert "— Lizenz: frei zugänglich (keine OER-Lizenz)\n" in text
    assert "creativecommons.org" not in text


def test_brackets_in_titles_and_urls_cannot_break_the_link() -> None:
    """Titles and URLs come from the repository: brackets in a title are escaped, a URL with spaces or parentheses
    goes in angle brackets, and angle brackets inside such a URL are percent-encoded so they cannot end it."""
    ref = replace(REFS[0], title="Arbeitsblatt [PDF] (Teil 1)", url="https://host.test/a b(c).pdf")
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())
    assert r"[**Arbeitsblatt \[PDF\] (Teil 1)**](<https://host.test/a b(c).pdf>)" in text
    angled, _ = render_collection_overview(
        INFO, [replace(REFS[0], url="https://host.test/a<b>c")], [], render_url=_render_url, options=OverviewOptions()
    )
    assert "(<https://host.test/a%3Cb%3Ec>)" in angled


def test_blocks_are_separated_by_a_blank_line_so_a_fence_parser_cannot_run_them_together() -> None:
    text, _ = render_collection_overview(INFO, REFS[:3], [], render_url=_render_url, options=OverviewOptions())
    assert ":::\n::: wlo-material" not in text
    assert text.count(":::\n\n::: wlo-material") == 2
    assert "-->\n\n::: wlo-material" in text  # the facet marker does not touch the first fence
    full, _ = render_collection_overview(INFO, REFS, SUBS_WITH_REFS, render_url=_render_url, options=OverviewOptions())
    assert "\n\n\n" not in full  # no stray blank runs anywhere in the part


def test_an_empty_collection_says_so_without_an_empty_block() -> None:
    text, _ = render_collection_overview(INFO, [], [], render_url=_render_url, options=OverviewOptions())
    assert "*Keine Inhalte gelistet.*" in text and "::: wlo-material" not in text


HOSTILE = "::: wlo-material" + chr(10) + ":::" + chr(10) + "danach"


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": HOSTILE},
        {"url": HOSTILE},
        {"original_id": HOSTILE},
        {"original_id": None, "id": HOSTILE},
        {"license_key": HOSTILE, "license_version": ""},
        {"license_key": "CC_BY", "license_version": HOSTILE},
        {"description": HOSTILE},
        {"keywords": (HOSTILE,)},
        {"description": "", "keywords": (), "resource_types": (HOSTILE,)},
        {"educational_contexts": (HOSTILE,)},
        {"subjects": (HOSTILE,)},
    ],
    ids=[
        "title",
        "url",
        "node-id",
        "reference-id",
        "licence",
        "licence-version",
        "description",
        "keywords",
        "resource-type",
        "level",
        "subject",
    ],
)
def test_no_value_of_a_material_can_open_or_close_a_fence_anywhere_in_the_part(overrides: dict[str, object]) -> None:
    """Every rendered value of a material comes from the repository, where an editor can type anything, and
    reaches part 3 in its block, in the key figures above the blocks, or in both. None may yield a line a fence
    parser reads as the start or end of a block: not through a line break, and not by opening a line - the
    metadata line starts with whatever the repository holds."""
    ref = replace(REFS[0], **overrides)
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())

    fences = [line for line in text.split(chr(10)) if line.lstrip().startswith(":::")]
    assert fences == ["::: wlo-material", ":::"]


def test_a_material_the_repository_cannot_resolve_keeps_its_title_unlinked_and_spares_the_others() -> None:
    """Without an own URL the title links the material's page in the repository, which needs a valid node id.
    A material without one must not take part 3 down: its title stays unlinked, the others render as usual."""
    broken = replace(REFS[0], url="", original_id=None, id="", title="Optik [Folie](https://host.test)")
    text, _ = render_collection_overview(
        INFO, [broken, REFS[1]], [], render_url=_checked_render_url, options=OverviewOptions()
    )
    assert chr(10) + "nodeId:" + chr(10) in text  # nothing to name, and no trailing space either
    assert chr(10) + r"**Optik \[Folie\](https://host.test)** — Lizenz: CC BY-NC-SA 3.0" + chr(10) in text
    assert text.count("::: wlo-material") == 2
    assert "[**Unterrichtsreihe zum Licht**](https://unterrichten.zum.de/wiki/Licht) — Lizenz: " in text
