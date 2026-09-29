"""Text of sources and repositories cannot put markup into the markdown of a compendium (audit 2026-09-28, SE-16 and
SE-21).

The rules copy sentences word for word, and the ZIM parser turns "&lt;" into "<": the article on cross-site scripting
brought a real ``<script>`` into part 1. Materials, their titles, addresses and authors, the lines of part 3 and two
labels of part 2 went in as typed. Every test renders the markdown with markdown-it, raw HTML let through, and asks
what came out (tests/markdown_safety.py).
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from libzim.writer import Creator

from app.compose.assembler import render_markdown
from app.domain.models import ArticleSection, Chunk, ChunkKind, Citation, Paragraph, ScoredChunk, Source
from app.domain.requests import GenerateRequest
from app.main import build_service
from app.sources.lehrplan.matcher import CurriculumMatch, MatchResult
from app.sources.lehrplan.render import RenderOptions, render_curricula
from app.sources.lehrplan.store import LehrplanRecord, NodeHit
from app.sources.lehrplan.stufen import Resolved
from app.sources.wlo.models import parse_collection, parse_reference
from app.sources.wlo.overview import OverviewOptions, render_collection_overview
from app.sources.zim.registry import ZimRegistry
from app.synthesis.actors import Actor, build_actors_section
from app.synthesis.extractive import synthesize
from app.synthesis.glossary import build_glossary
from app.synthesis.safe_markdown import defuse, escape_text, unescape
from app.synthesis.sources_section import build_sources_section
from app.templates.manager import TemplateManager
from tests.conftest import FIXTURES, SAMPLE_META, HtmlItem, make_settings
from tests.markdown_safety import render, tags, unsafe

BS, CR, LF = chr(92), chr(13), chr(10)  # spelled out: tools on the way turn escapes in test text into other signs
# What a source, a material or a repository may carry: markup that runs or loads something, markup that hides or links,
# and lines that read as structure
FOREIGN = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(3)">Klick</a>',
    "a <b>fett</b> c",
    "Vorher <!-- versteckt den Rest",
    "[Blatt](javascript:alert(document.cookie))",
    "![Bild](//evil.example/t.png)",
    '[5]: //evil.example/x "Titel"',
    "Text [mit [verschachtelten] Klammern](javascript:alert(4))",
    BS + "[Link](javascript:alert(2))",
    "<https://evil.example/autolink>",
    "&lt;script&gt; als Entität",
    "`<p>` ist ein Tag",
    "## Überschrift aus dem Material",
    "- ein Listenpunkt",
    "1. erster Punkt",
    "```",
    "---",
    "| a | b |",
    "Zeile eins" + CR + "# Überschrift nach CR",
    # emphasis: WLO descriptions gender with an asterisk, and CommonMark reads one inside a word (audit 2026-09-29, T2)
    "Für Lehrer*innen sowie Schüler*innen",
    "__init__ rechnet 5*3*2 und _kursiv_",
]
FIX = Path(__file__).parent / "fixtures" / "wlo"


def shown(markdown: str) -> str:
    """The text a reader sees, whitespace collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", render(markdown))).split())


@pytest.mark.parametrize("text", FOREIGN)
def test_escaped_text_shows_as_typed_and_nothing_else(text: str) -> None:
    markdown = escape_text(text)

    assert unsafe(markdown) == []
    assert tags(markdown) == ["p"]  # no heading, list, rule, code, table or link
    assert shown(markdown) == " ".join(text.split())
    assert unescape(markdown) == text.replace(CR, LF)


def test_an_underscore_that_cannot_open_emphasis_stays_as_it_is() -> None:
    """An underscore after a letter or digit, or before a blank, opens no emphasis in CommonMark, and an autolink of
    GFM keeps the backslashes of an address: the addresses the sources block prints as text stay as they are (audit
    2026-09-29, T2)."""
    for address in ("https://de.wikipedia.org/wiki/Isaac_Newton", "https://de.wikipedia.org/wiki/Brechung_(Physik)"):
        assert escape_text(address) == address
    assert (
        shown(escape_text("snake_case_name und Merkur_(Planet)_ und _")) == "snake_case_name und Merkur_(Planet)_ und _"
    )


@pytest.mark.parametrize("text", FOREIGN)
def test_defused_markdown_runs_nothing(text: str) -> None:
    assert unsafe(defuse(text)) == []
    assert defuse(escape_text(text)) == escape_text(text)  # an escape stays one


def test_a_reference_definition_cannot_turn_the_evidence_numbers_into_links() -> None:
    document = 'Ein Satz aus der Quelle [5].\n\n[5]: //evil.example/x "Titel"\n\n| Beleg |\n| :---: |\n| [5] |'

    assert unsafe(document) != []  # the number would link to the attacker, in the text and in the table
    assert unsafe(defuse(document)) == []


OWN = LF.join(
    [
        "Satz aus der Quelle [3].",
        "",
        "<!-- f: Evidenzgrad=Modellwissen -->Ein Satz des Modells. [Modellwissen]<!-- /f -->",
        "",
        "- **[Optik](https://de.wikipedia.org/wiki/Optik)** — Wikipedia, Nachschlagewerk",
        "- [Linse](<https://de.wikipedia.org/wiki/Linse_(Optik)>) · nodeId: 1",
        "",
        "| Beleg | Quelle |",
        "| :---: | :--- |",
        "| [1] | [Optik](HTTPS://de.wikipedia.org/wiki/Optik) |",
        "",
        "<!-- f: Sammlung=x; Fach=Physik -->",
        "- Inhalt: **Blatt** · nodeId: 2",
        "<!-- /f -->",
    ]
)


def test_defuse_keeps_what_the_service_writes() -> None:
    assert unsafe(OWN) == []
    assert defuse(OWN) == OWN


def _source(**fields: object) -> Source:
    values: dict[str, object] = {"source_id": "wlo:1", "project": "wlo_material", "title": "Blatt", "url": ""}
    return Source(**{**values, **fields})  # type: ignore[arg-type]


def test_part_1_prints_foreign_sentences_lists_and_tables_as_typed() -> None:
    sentences = [
        "Das Element <script>alert(1)</script> führt im Browser ein Skript aus.",
        "Ein Bild wie <img src=x onerror=alert(1)> lädt bei einem Fehler Code nach.",
        "Der Verweis [Blatt](javascript:alert(document.cookie)) führt ins Leere hinein.",
    ]
    source = _source(source_id="wikipedia:XSS", project="wikipedia", url="https://de.wikipedia.org/wiki/XSS")
    chunks = [
        Chunk(chunk_id="c1", source_id=source.source_id, heading="Beispiel", text=" ".join(sentences)),
        Chunk(
            chunk_id="c2",
            source_id=source.source_id,
            heading="Liste",
            kind=ChunkKind.LIST,
            text="<img src=x onerror=alert(2)>\n## keine Überschrift\n[x](javascript:alert(3))",
        ),
        Chunk(
            chunk_id="c3",
            source_id=source.source_id,
            heading="Tabelle",
            kind=ChunkKind.TABLE,
            text="Kopf | <b>Spalte</b>\n<script>x</script> | [y](javascript:alert(4))",
        ),
    ]

    text, _ = synthesize(
        [ScoredChunk(chunk=chunk, score=1.0) for chunk in chunks], {source.source_id: source}, 0, set(), True
    )

    assert unsafe(text) == []
    assert not {"h2", "script", "img"} & set(tags(text))
    for sentence in sentences:
        assert sentence in unescape(text)  # word for word once the escapes are read back


def test_the_sources_block_links_only_web_addresses_and_prints_the_rest_as_typed() -> None:
    material = _source(
        title="Blatt <!-- versteckt",
        url="javascript:alert(document.cookie)",
        authors=["<img src=x onerror=alert(1)>", "[Autor](javascript:alert(2))"],
        license="CC BY <b>4.0</b>",
        zim_file="archiv`<img src=x onerror=alert(3)>`.zim",
        entry_path="A/`x` <script>",
        reference_lines=["[Weblink](javascript:alert(5))", "<iframe src=//evil.example>"],
    )
    citation = Citation(
        number=1,
        source_id=material.source_id,
        chunk_id="c1",
        source_title="<svg onload=alert(6)>",
        source_url="javascript:alert(7)",
        section_heading="![x](//evil.example/t.png)",
        snippet="Ein Auszug mit <script>alert(8)</script> | und einer Spalte",
    )

    markdown = build_sources_section([material], [citation], facets_visible=True)

    assert unsafe(markdown) == []
    assert "javascript:" not in "".join(re.findall(r'href="([^"]*)"', render(markdown)))


def test_the_glossary_prints_titles_topic_and_definitions_as_typed() -> None:
    lead = ArticleSection(
        heading="",
        path=[],
        level=0,
        paragraphs=[
            Paragraph(text="Optik <img src=x onerror=alert(1)> ist die Lehre vom Licht und seiner Ausbreitung.")
        ],
    )
    primary = _source(
        source_id="wikipedia:Optik",
        project="wikipedia",
        title="Optik <script>",
        url="javascript:alert(2)",
        is_primary=True,
        sections=[lead],
    )
    side = primary.model_copy(
        update={"source_id": "wikipedia:Linse", "title": "[Linse](javascript:x)", "is_primary": False}
    )

    markdown = build_glossary("<b>Optik</b>", primary, [primary, side], ["<i>Lichtlehre</i>"])

    assert markdown and unsafe(markdown) == []


def test_the_actors_block_prints_names_and_summaries_as_typed() -> None:
    actor = Actor(
        name="Ernst <img src=x onerror=alert(1)> Abbe",
        kind="Person",
        summary="[Physiker](javascript:alert(2)) <script>",
        url="javascript:alert(3)",
        functions=["<b>Wissenschaft</b>"],
        zeitbezug="<i>1840</i>",
    )

    markdown = build_actors_section([actor], facets_visible=True)

    assert unsafe(markdown) == []


def _load(name: str) -> dict:  # type: ignore[type-arg]
    data: dict = json.loads((FIX / name).read_text(encoding="utf-8"))  # type: ignore[type-arg]
    return data


def test_part_3_prints_titles_descriptions_keywords_and_licences_as_typed() -> None:
    info = parse_collection(_load("collection_optik.json"))
    info = replace(info, title="<script>alert(1)</script>", description="## Mitte\n<img src=x onerror=alert(2)>")
    ref = parse_reference(_load("references_optik_page1.json")["references"][0])
    hostile = replace(
        ref,
        title="Blatt <svg onload=alert(3)>",
        url="javascript:alert(document.cookie)",
        description="[Arbeitsblatt](javascript:alert(4)) mit <img src=x onerror=alert(5)>",
        keywords=("<b>Licht</b>", "![t](//evil.example/t.png)"),
        license_key="<i>CC_BY</i>",
        license_version="<b>4.0</b>",
    )
    untitled = replace(ref, title="<script>ohne Adresse</script>", url="")

    markdown, _ = render_collection_overview(
        info,
        [hostile, untitled],
        [],
        render_url=lambda node_id: f"https://repo.test/render/{node_id}",
        options=OverviewOptions(),
    )

    assert unsafe(markdown) == []


def test_part_2_prints_school_types_and_grades_as_typed() -> None:
    """SE-21: title, elements and area went through plain_label, the school types and the grade did not."""
    curriculum = LehrplanRecord(
        iri="https://lp-sachsen.org/resource/523",
        label="Physik",
        bundesland_code="SN",
        bundesland="Sachsen",
        schularten=["Gymnasium <!-- versteckt", "[Oberschule](javascript:alert(1))", "<img src=x onerror=alert(2)>"],
        schulfaecher=["Physik"],
    )
    hit = NodeHit(
        iri="https://lp.test/sn:k9",
        label="Lichtbrechung",
        rollen=["inhalt"],
        parent_iri=None,
        parent_label="Lernbereich 9",
        jahrgangsstufen=[],
        depth=1,
        lehrplan=curriculum,
        matched_in="label",
    )
    match = CurriculumMatch(
        hit=hit,
        keyword="Optik",
        schulstufe=Resolved("<b>Sek I</b>", "Daten"),
        klassenstufe=Resolved("<script>Klasse 9</script>", "Daten"),
        score=0,
    )
    result = MatchResult(keywords=["Optik"], subject_terms=["physik"], matches=[match], total_hits=1, excluded_noise=0)

    meta = {"harvested_at": "2026-09-17T12:00:00+00:00", "counts": json.dumps({"SN": 1})}
    markdown, _ = render_curricula(result, meta=meta, options=RenderOptions())

    assert unsafe(markdown) == []


LONG = "[Blatt](javascript:alert(4)) " * 20  # long enough that YAML folds it


def test_the_topic_is_printed_as_typed_in_the_heading_and_kept_exactly_in_the_frontmatter() -> None:
    topic = "<img src=x onerror=alert(1)> & [Optik](javascript:alert(2))"
    template = TemplateManager().get("sc26")

    markdown = render_markdown(
        topic=topic,
        frontmatter={"topic": topic, "sources_snapshot": [{"title": "<script>alert(3)</script>", "note": LONG}]},
        template=template,
        sections=[],
        sources=[],
        facets_visible=False,
    )

    assert unsafe(markdown) == []
    block = markdown.split("---")[1]
    assert yaml.safe_load(block)["topic"] == topic  # the frontmatter keeps the value, only its spelling is inert
    assert yaml.safe_load(block)["sources_snapshot"][0]["title"] == "<script>alert(3)</script>"
    assert yaml.safe_load(block)["sources_snapshot"][0]["note"] == LONG  # folded over lines by the dumper


def test_a_whole_compendium_on_an_article_that_quotes_code_runs_nothing(tmp_path: Path) -> None:
    """The article on cross-site scripting quotes a script as its example, and the ZIM parser turns its "&lt;" into
    "<": the rules printed it as a real tag. Here the Optik article of the samples quotes such code first."""
    quoted = (
        "Ein Beispiel wie &lt;script&gt;alert(1)&lt;/script&gt; oder &lt;img src=x onerror=alert(2)&gt; zeigt, wie "
        "eine Seite Code zitiert, und [Blatt](javascript:alert(3)) steht als Text daneben. "
    )
    html = (FIXTURES / "wikipedia" / "Optik.html").read_text(encoding="utf-8").replace("<p>", "<p>" + quoted, 1)
    meta = SAMPLE_META["wikipedia"]
    archive = tmp_path / str(meta["file"])
    with Creator(str(archive)).config_indexing(True, "deu") as creator:
        creator.set_mainpath("Optik")
        for key in ("Name", "Title", "Creator", "Publisher", "Date", "Description", "Language", "Flavour", "Tags"):
            creator.add_metadata(key, str(meta[key]))
        creator.add_item(HtmlItem("Optik", "Optik", html))
    settings = make_settings([archive], tmp_path / "state", zim_required="wikipedia_de_sample")
    service = build_service(settings, ZimRegistry(settings.zim_path_list), TemplateManager(tmp_path / "templates"))

    result = service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))

    assert "<script>alert(1)</script>" in unescape(result.markdown)  # the quote is in part 1, as typed
    assert unsafe(result.markdown) == []
