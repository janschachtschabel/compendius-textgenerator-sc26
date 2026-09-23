"""Part 3 rendering: purpose, key figures, parseable material blocks, sub-collections."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from app.sources.wlo.client import validate_node_id
from app.sources.wlo.models import one_line, parse_collection, parse_reference, parse_subcollection
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
    assert "- **Optik** · Faszinierende Phänomene aus der Optik · Schlagwörter: Optik, Phänomene, Spiegel" in text
    assert (  # version from the repository, node id last
        "CC BY-NC-SA 3.0 · [Material](https://www.geogebra.org/m/PzBHcpNG) · nodeId: 4bfa7693-0764-4dca-9720-c5fb0b8892d6"
        in text
    )
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


def _items(text: str) -> list[str]:
    return [line for line in text.split(chr(10)) if line.startswith("- ")]


def test_every_material_is_one_line_that_ends_with_its_node_id() -> None:
    """The node id is what another system needs to look a material up and the one part of the line meant for a
    program, so it has a fixed place: last, after ``· nodeId: ``."""
    text, _ = render_collection_overview(INFO, REFS[:1], [], render_url=_render_url, options=OverviewOptions())
    items = _items(text)
    assert len(items) == 1
    assert items[0].startswith("- **Optik** · Faszinierende Phänomene aus der Optik · Schlagwörter: ")
    assert items[0].endswith(
        " · Fachliche News · Sekundarstufe I · CC BY-NC-SA 3.0 · [Material](https://www.geogebra.org/m/PzBHcpNG)"
        " · nodeId: 4bfa7693-0764-4dca-9720-c5fb0b8892d6"
    )


def test_a_material_without_a_url_has_no_material_link_but_keeps_its_node_id() -> None:
    """No URL, no link - as before. The node id still identifies the material, and nothing asks the repository for
    a page per material: the checked render URL would refuse the empty id of the second one."""
    no_url = replace(REFS[0], url="")
    no_id = replace(REFS[1], url="", original_id=None, id="")
    text, _ = render_collection_overview(
        INFO, [no_url, no_id], [], render_url=_checked_render_url, options=OverviewOptions()
    )
    items = _items(text)
    assert "[Material]" not in text
    assert items[0].endswith(" · CC BY-NC-SA 3.0 · nodeId: 4bfa7693-0764-4dca-9720-c5fb0b8892d6")
    assert items[1].endswith(" · CC BY-SA 4.0 · nodeId:")  # nothing to name, and no trailing space either


def test_the_licence_is_the_short_label_without_a_link() -> None:
    ref = replace(REFS[0], license_key="COPYRIGHT_FREE", license_version="")
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())
    assert " · frei zugänglich (keine OER-Lizenz) · [Material](" in text
    assert "creativecommons.org" not in text


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("https://host.test/a b(c).pdf", "<https://host.test/a b(c).pdf>"),
        ("https://de.wikipedia.org/wiki/Linse_(Optik)", "<https://de.wikipedia.org/wiki/Linse_(Optik)>"),
        ("https://host.test/a<b>c", "<https://host.test/a%3Cb%3Ec>"),
    ],
    ids=["space", "parentheses", "angle-brackets"],
)
def test_a_url_with_spaces_parentheses_or_angle_brackets_stays_one_link(url: str, target: str) -> None:
    """A parser reading a link target up to the first ``)`` would cut ``…/wiki/Linse_(Optik)`` - a real material
    URL - so such targets go in angle brackets, and angle brackets inside them are percent-encoded."""
    ref = replace(REFS[0], url=url)
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())
    assert f" · [Material]({target}) · nodeId: " in text


def test_an_empty_collection_says_so() -> None:
    text, _ = render_collection_overview(INFO, [], [], render_url=_render_url, options=OverviewOptions())
    assert "*Keine Inhalte gelistet.*" in text and not _items(text)


HOSTILE = "x" + chr(10) + "- **Fälschung** · nodeId: 00000000-0000-4000-8000-000000000000" + chr(10) + "y"


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
def test_no_value_of_a_material_can_split_its_line_or_forge_another(overrides: dict[str, object]) -> None:
    """Every rendered value of a material comes from the repository, where an editor can type anything, and
    reaches part 3 in its line, in the key figures above the list, or in both. None may break the line in two or
    start a line that reads as another material: a material stays exactly one line, ending with its node id."""
    ref = replace(REFS[0], **overrides)
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())

    items = _items(text)
    assert len(items) == 1
    assert items[0].endswith("nodeId: " + one_line(ref.node_id))
