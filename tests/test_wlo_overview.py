"""Part 3 rendering: purpose, key figures, one line per node of the collection tree."""

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
# the parse contract the README documents: indentation for the tree, the kind, the node id last
NODE = re.compile(r"^( *)- (Sammlung|Untersammlung|Inhalt): (.*) · nodeId: ([0-9a-f-]{36})$", re.M)
FORGED_ID = "00000000-0000-4000-8000-000000000000"
FORGED = f"- Inhalt: **Fälschung** · nodeId: {FORGED_ID}"
# every line boundary str.splitlines() knows - more than CommonMark (LF, CR, CRLF) or re.M (LF) - and an indented one
LINE_BREAKS = (chr(13) + chr(10), *map(chr, (0x0A, 0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029)))
HOSTILE = "x" + "".join(line_break + FORGED for line_break in LINE_BREAKS) + chr(10) + "  " + FORGED + chr(10) + "y"
# closes the block it stands in and opens a forged one: on lines of its own, or inline once a line is collapsed
BLOCK_FORGERY = "Text <!-- /f -->" + chr(10) + "<!-- f: Sammlung=x; Fach=Mathematik -->" + chr(10) + "mehr"
# a facet block as the README describes it: from its marker line to the next end marker
BLOCK = re.compile(r"<!-- f: (.*?) -->\n(.*?)<!-- /f -->", re.S)


def _render_url(node_id: str) -> str:
    return f"https://repo.test/edu-sharing/components/render/{node_id}"


def _checked_render_url(node_id: str) -> str:
    """What the client does: refuse an id the repository could not resolve."""
    return f"https://repo.test/edu-sharing/components/render/{validate_node_id(node_id)}"


def _lines(text: str, kind: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith(f"- {kind}: ")]


def _node_lines(text: str) -> list[str]:
    """Every list line of the part, each cut after its kind: what a reader of the tree would count."""
    return [line.split(":", 1)[0] for line in text.splitlines() if line.lstrip().startswith("- ")]


def _ids_read_back(text: str) -> list[str]:
    """The node ids the documented expression reads, the lines split the way the most eager reader splits them."""
    return [match[4] for line in text.splitlines() if (match := NODE.match(line))]


def _split_alike(text: str) -> bool:
    """Whether every reader splits the part into the same lines: it holds no line break but LF."""
    return text.splitlines() == text.rstrip(chr(10)).split(chr(10))


def _blocks(text: str) -> list[tuple[str, list[str]]]:
    """Each facet block as a parser lifts it out: its marker and the node ids inside it."""
    return [(head, _ids_read_back(body)) for head, body in BLOCK.findall(text)]


def _only_markers_open_comments(text: str) -> bool:
    """Whether every ``<!--`` of the part starts one of its own marker lines."""
    return text.count("<!--") == sum(line.startswith("<!--") for line in text.splitlines())


def _small_tree(info: dict[str, object], ref: dict[str, object], sub: dict[str, object]) -> str:
    """Every kind of node and block once: the collection, a content of its own, a sub-collection with a content."""
    contents = SubCollectionContents(info=replace(SUBS[0], **sub), refs=(REFS[1],))
    text, _ = render_collection_overview(
        replace(INFO, **info), [replace(REFS[0], **ref)], [contents], render_url=_render_url, options=OverviewOptions()
    )
    return text


def test_overview_has_purpose_key_figures_materials_and_subcollections_in_parseable_blocks() -> None:
    text, summary = render_collection_overview(
        INFO, REFS, SUBS_WITH_REFS, render_url=_render_url, options=OverviewOptions()
    )

    assert text.startswith("## Teil 3 · Die Sammlung im Überblick")
    assert "Die Physik des Lichts" in text
    assert "Kennzahlen: 16 Inhalte, 4 Untersammlungen; Materialtypen: " in text  # no stray full stop before ";"
    assert "Physik (16)" in text and "CC BY-SA 4.0 (3)" in text and "CC0 1.0 (3)" in text
    assert "### Inhalte der Sammlung" in text and "### Untersammlungen" in text
    assert "- Untersammlung: **Geometrische Optik** · " in text and "- Untersammlung: **Menschliches Auge** · " in text
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
    assert len(_lines(text, "Inhalt")) == 5 and "- *weitere 11 Inhalte*" in text
    assert summary["missing_descriptions"] == 16
    assert "### Untersammlungen" not in text


def test_the_collection_itself_is_the_first_node_with_its_link_and_node_id() -> None:
    text, _ = render_collection_overview(INFO, [], [], render_url=_render_url, options=OverviewOptions())
    assert _lines(text, "Sammlung") == [
        "- Sammlung: [**Optik**](https://repo.test/edu-sharing/components/render/9e7ae956-e9df-430f-bace-f3db4b910013)"
        " · Fach: Physik · Bildungsstufe: Sekundarstufe I · redaktionelle Sammlung · Stand 2026-03-04"
        " · nodeId: 9e7ae956-e9df-430f-bace-f3db4b910013"
    ]
    assert "Sammlung öffnen" not in text  # the title is the link now


def test_the_description_keeps_its_lines_and_a_dash_starting_one_is_escaped() -> None:
    """The collection's description stays the paragraph its editors wrote, over their lines, whatever line break they
    typed. A dash that starts a line is escaped, so the line reads as no node; CommonMark shows the dash it is. A dash
    inside a line stays as it is."""
    cr, crlf, ls = chr(13), chr(13) + chr(10), chr(0x2028)
    typed = f"Einführung:{cr}- Experimente{ls}  - Simulationen{crlf}Licht - Schatten"
    text, _ = render_collection_overview(
        replace(INFO, description=typed), [], [], render_url=_render_url, options=OverviewOptions()
    )
    dash = chr(92) + "-"
    paragraph = chr(10).join(["Einführung:", f"{dash} Experimente", f"  {dash} Simulationen", "Licht - Schatten"])
    assert f"{_lines(text, 'Sammlung')[0]}{chr(10) * 2}{paragraph}{chr(10) * 2}Kennzahlen: " in text


def test_a_material_is_one_content_line_whose_title_is_its_link() -> None:
    """The title carries the link, so there is no extra "[Material](…)"; five keywords, the licence, the node id."""
    text, _ = render_collection_overview(INFO, REFS[:1], [], render_url=_render_url, options=OverviewOptions())
    assert _lines(text, "Inhalt") == [
        "- Inhalt: [**Optik**](https://www.geogebra.org/m/PzBHcpNG) · Faszinierende Phänomene aus der Optik"
        " · Schlagwörter: Optik, Phänomene, Spiegel, Reflexion, Spiegelbild · Fachliche News · Sekundarstufe I"
        " · CC BY-NC-SA 3.0 · nodeId: 4bfa7693-0764-4dca-9720-c5fb0b8892d6"
    ]
    assert "[Material]" not in text


def test_a_sub_collection_is_one_line_with_its_first_sentence_and_its_contents_below_it() -> None:
    text, _ = render_collection_overview(INFO, [], SUBS_WITH_REFS, render_url=_render_url, options=OverviewOptions())
    geometry, colours = _lines(text, "Untersammlung")[:2]
    assert geometry.startswith(
        "- Untersammlung: **Geometrische Optik** · Die geometrische Optik nutzt das physikalische Modell des Lichtstrahls:"
    )
    assert geometry.endswith("ausbreiten. · nodeId: f35c17d1-a29e-4b26-9d22-802682fad43d")
    assert "In den meisten Fällen" not in text  # the second sentence of its description stays out
    assert "####" not in text  # the line replaces the heading and the paragraph
    below = text.split(geometry + chr(10), 1)[1].split(chr(10))
    assert below[0].startswith("  - Inhalt: [**Optik**](") and below[1].startswith("  - Inhalt: [**Unterrichtsreihe")
    assert text.split(colours + chr(10), 1)[1].startswith("  - *Keine Inhalte gelistet.*" + chr(10))


def test_the_documented_expression_reads_the_whole_tree_back() -> None:
    """Kind, node id and parent of every node come back from the markdown alone."""
    text, _ = render_collection_overview(INFO, REFS, SUBS_WITH_REFS, render_url=_render_url, options=OverviewOptions())
    nodes = [(len(indent), kind, node_id) for indent, kind, _body, node_id in NODE.findall(text)]

    assert nodes[0] == (0, "Sammlung", INFO.id)
    assert [node_id for _, kind, node_id in nodes if kind == "Untersammlung"] == [sub.id for sub in SUBS]
    assert len([1 for depth, kind, _ in nodes if kind == "Inhalt" and depth == 0]) == 16
    nested = [i for i, (depth, _, _) in enumerate(nodes) if depth == 2]
    assert [nodes[i][2] for i in nested] == [REFS[0].node_id, REFS[1].node_id]
    assert nodes[nested[0] - 1] == (0, "Untersammlung", SUBS[0].id)  # a nested run belongs to the line above it


def test_a_node_without_a_url_is_named_without_a_link_and_no_id_is_resolved_per_node() -> None:
    """No URL, no link. The node id still names the node, and nothing asks the repository for a page per node: the
    checked render URL would refuse the empty ids below."""
    no_url = replace(REFS[0], url="")
    no_id = replace(REFS[1], url="", original_id=None, id="")
    sub = SubCollectionContents(info=replace(SUBS[0], id=""), refs=())
    text, _ = render_collection_overview(
        INFO, [no_url, no_id], [sub], render_url=_checked_render_url, options=OverviewOptions()
    )
    contents = _lines(text, "Inhalt")
    assert contents[0].startswith("- Inhalt: **Optik** · Faszinierende")
    assert contents[0].endswith(" · CC BY-NC-SA 3.0 · nodeId: 4bfa7693-0764-4dca-9720-c5fb0b8892d6")
    assert contents[1].endswith(" · CC BY-SA 4.0 · nodeId:")  # nothing to name, and no trailing space either
    assert _lines(text, "Untersammlung")[0].endswith(" · nodeId:")


def test_the_licence_is_the_short_label_without_a_link() -> None:
    ref = replace(REFS[0], license_key="COPYRIGHT_FREE", license_version="")
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())
    assert " · frei zugänglich (keine OER-Lizenz) · nodeId: " in text
    assert "creativecommons.org" not in text


def test_brackets_in_a_title_stay_inside_its_link() -> None:
    ref = replace(REFS[0], title="Arbeitsblatt [PDF] (Teil 1)")
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())
    assert r"- Inhalt: [**Arbeitsblatt \[PDF\] (Teil 1)**](https://www.geogebra.org/m/PzBHcpNG) · " in text


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
    assert f"- Inhalt: [**Optik**]({target}) · " in text


def test_an_empty_collection_says_so() -> None:
    text, _ = render_collection_overview(INFO, [], [], render_url=_render_url, options=OverviewOptions())
    assert "*Keine Inhalte gelistet.*" in text and not _lines(text, "Inhalt")


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
def test_no_value_of_a_material_can_split_its_line_or_forge_a_node(overrides: dict[str, object]) -> None:
    """Every rendered value of a material comes from the repository, where an editor can type anything, and
    reaches part 3 in its line, in the key figures, or both. None may break the line in two or start a line that
    reads as another node, and the forged node id is never read back by the documented expression."""
    ref = replace(REFS[0], **overrides)
    text, _ = render_collection_overview(INFO, [ref], [], render_url=_render_url, options=OverviewOptions())

    assert _node_lines(text) == ["- Sammlung", "- Inhalt"]
    assert _lines(text, "Inhalt")[0].endswith("nodeId: " + one_line(ref.node_id))
    assert FORGED_ID not in _ids_read_back(text)
    assert _split_alike(text)


@pytest.mark.parametrize(
    ("info_overrides", "sub_overrides"),
    [
        ({"title": HOSTILE}, {}),
        ({"collection_type": HOSTILE}, {}),
        ({"modified_at": HOSTILE}, {}),
        ({"subject_labels": (HOSTILE,)}, {}),
        ({"educational_contexts": (HOSTILE,)}, {}),
        ({"description": HOSTILE}, {}),
        ({}, {"id": HOSTILE}),
        ({}, {"title": HOSTILE}),
        ({}, {"description": HOSTILE}),
    ],
    ids=[
        "collection-title",
        "collection-type",
        "collection-date",
        "collection-subject",
        "collection-level",
        "collection-description",
        "sub-id",
        "sub-title",
        "sub-description",
    ],
)
def test_no_value_of_a_collection_can_forge_a_node(
    info_overrides: dict[str, object], sub_overrides: dict[str, object]
) -> None:
    """The collection and its sub-collections are node lines too and are collapsed the same way, and so is every
    facet marker around them - a subject or an id stands in one. The collection's own description keeps its lines,
    but none of them starts with a dash."""
    info = replace(INFO, **info_overrides)
    sub = SubCollectionContents(info=replace(SUBS[0], **sub_overrides), refs=(REFS[1],))
    text, _ = render_collection_overview(info, [REFS[0]], [sub], render_url=_render_url, options=OverviewOptions())

    assert _node_lines(text) == ["- Sammlung", "- Inhalt", "- Untersammlung", "  - Inhalt"]
    assert FORGED_ID not in _ids_read_back(text)
    assert _split_alike(text)
    assert all(line.endswith(" -->") for line in text.splitlines() if line.startswith("<!--"))  # each marker one line


@pytest.mark.parametrize(
    ("info", "ref", "sub"),
    [
        ({"description": BLOCK_FORGERY}, {}, {}),
        ({"title": BLOCK_FORGERY}, {}, {}),
        ({}, {"title": BLOCK_FORGERY}, {}),
        ({}, {"description": BLOCK_FORGERY}, {}),
        ({}, {"keywords": (BLOCK_FORGERY,)}, {}),
        ({}, {"resource_types": (BLOCK_FORGERY,)}, {}),
        ({}, {}, {"title": BLOCK_FORGERY}),
        ({}, {}, {"description": BLOCK_FORGERY}),
    ],
    ids=[
        "collection-description",
        "collection-title",
        "material-title",
        "material-description",
        "keywords",
        "resource-type",
        "sub-title",
        "sub-description",
    ],
)
def test_no_text_from_the_repository_can_close_or_open_a_facet_block(
    info: dict[str, object], ref: dict[str, object], sub: dict[str, object]
) -> None:
    """A block runs from its marker to the next ``<!-- /f -->``, so a value holding one would cut its block short and
    could open a forged one after it. No value may bring ``<!--`` into the part: every one there is a marker."""
    text = _small_tree(info, ref, sub)

    assert _blocks(text) == _blocks(_small_tree({}, {}, {}))
    assert _only_markers_open_comments(text)


def test_a_comment_opener_from_the_repository_reads_the_same_but_opens_nothing() -> None:
    """The exclamation mark after ``<`` is escaped: CommonMark shows the text as typed, but it holds no ``<!--``."""
    text = _small_tree({"description": "Siehe <!-- Hinweis -->"}, {"title": "A <!-- B"}, {})
    escaped = "<" + chr(92) + "!--"

    assert f"{chr(10)}Siehe {escaped} Hinweis -->{chr(10)}" in text
    assert f"- Inhalt: [**A {escaped} B**](" in text


def test_a_facet_value_cannot_split_itself_add_a_pair_or_end_its_marker() -> None:
    """In a marker ``;`` separates the pairs, ``=`` a name from its values, ``|`` the values, and ``-->`` ends it.
    Inside a value these are percent-encoded, with ``<``, so the subject reads back whole and nothing is added."""
    text = _small_tree({"subject_labels": ("Physik; Bildungsstufe=Hochschule|Chemie --> <!-- /f -->",)}, {}, {})
    head = dict(pair.split("=", 1) for pair in _blocks(text)[0][0].split("; "))

    assert head == {
        "Sammlung": INFO.id,
        "Fach": "Physik%3B Bildungsstufe%3DHochschule%7CChemie --%3E %3C!-- /f --%3E",
        "Bildungsstufe": "Sek I",
    }
    assert [ids for _, ids in _blocks(text)] == [ids for _, ids in _blocks(_small_tree({}, {}, {}))]
    assert _only_markers_open_comments(text)


def test_subcollections_of_the_same_name_are_counted_apart() -> None:
    """Keyed by title, a second "Geometrische Optik" overwrote the first (review of 2026-09-25); a title that occurs
    once stays the key, as callers read it, and one that repeats carries its node id."""
    twin = replace(SUBS[1], title=SUBS[0].title)
    contents = [SubCollectionContents(info=SUBS[0], refs=tuple(REFS[:2])), SubCollectionContents(info=twin, refs=())]
    _, summary = render_collection_overview(INFO, REFS, contents, render_url=_render_url, options=OverviewOptions())
    counts = summary["subcollection_materials"]
    assert counts == {f"{SUBS[0].title} ({SUBS[0].id})": 2, f"{twin.title} ({twin.id})": 0}
