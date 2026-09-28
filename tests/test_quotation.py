"""The rules quote: every sentence of a block word for word from the paragraph its marker names (audit TE-04).

Only extraction=llm, which no profile uses, was checked for it (tests/test_pipeline_extraction.py); the default
path held the promise when the audit counted 312 sentences on 12 topics, but nothing kept it. And the rendering of a
table never ran.
"""

from __future__ import annotations

import pytest

from app.domain.models import Chunk, ChunkKind, ScoredChunk, SectionStatus, Source
from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.synthesis.extractive import TABLE_ROWS_MAX, _render_table, synthesize, usable_sentences
from app.synthesis.safe_markdown import unescape

# The topics of the sample archives (tests/fixtures/zim_html)
TOPICS = (
    "Optik",
    "Linse",
    "Brechung",
    "Geometrische Optik",
    "Lichtmikroskop",
    "Ernst Abbe",
    "Photosynthese",
    "Demokratie",
    "Programmiersprache",
    "Sinfonie",
    "Regenbogen",
    "Brille",
)


def _quotes(body: str, paragraph: str) -> bool:
    """Whether ``body`` is whole sentences of ``paragraph``, word for word and in its order - some may be left out."""
    rest = body
    for sentence in usable_sentences(paragraph):
        if rest == sentence:
            return True
        if rest.startswith(sentence + " "):
            rest = rest[len(sentence) + 1 :]
    return False


@pytest.mark.parametrize("topic", TOPICS)
def test_every_rule_based_block_quotes_the_paragraphs_it_cites(service: CompendiumService, topic: str) -> None:
    paragraphs = {
        chunk.chunk_id: chunk.text for chunk in service.prepare(GenerateRequest(topic=topic, parts=["world"])).chunks
    }
    result = service.generate(GenerateRequest(topic=topic, parts=["world"], preset="llm-free"))
    quoted = 0
    for section in result.sections:
        if section.status is not SectionStatus.EXTRACTIVE:  # the generated blocks: sources, glossary, actors
            continue
        for line, citation in zip(section.text.split("\n\n"), section.citations, strict=True):
            body = unescape(line.rsplit(" [", 1)[0])  # the words as typed, without the escapes of the markdown
            if body.startswith(("- ", "| ")):  # a list or a table is taken whole
                continue
            assert _quotes(body, paragraphs[citation.chunk_id]), (topic, section.slot_id, body[:120])
            quoted += 1
    assert quoted, f"{topic}: no block quoted anything, so this proves nothing"


def test_a_table_gets_its_first_row_as_header_and_short_rows_are_filled() -> None:
    text = "Farbe | Wellenlänge | Frequenz\nRot | 700 nm"
    assert _render_table(text) == "| Farbe | Wellenlänge | Frequenz |\n| --- | --- | --- |\n| Rot | 700 nm |  |"


def test_a_long_table_keeps_its_first_rows_and_text_without_cells_stays_as_it_is() -> None:
    rows = "\n".join(f"Zeile {n} | {n}" for n in range(20))
    assert _render_table(rows).count("\n") == TABLE_ROWS_MAX  # header, separator and the rows after the header
    assert _render_table("kein Tabellentext") == "kein Tabellentext"


def test_a_table_paragraph_becomes_one_cited_table_in_its_block() -> None:
    source = Source(source_id="wikipedia:Licht", project="wikipedia", title="Licht", url="https://de.wikipedia.org/")
    chunk = Chunk(
        chunk_id="wikipedia:Licht:c007",
        source_id=source.source_id,
        heading="Spektrum",
        heading_path=["Spektrum"],
        heading_level=2,
        text="Farbe | Wellenlänge\nRot | 700 nm",
        kind=ChunkKind.TABLE,
    )
    text, citations = synthesize(
        [ScoredChunk(chunk=chunk, score=1.0, matcher="policy")], {source.source_id: source}, 0, set()
    )
    assert text == "| Farbe | Wellenlänge |\n| --- | --- |\n| Rot | 700 nm | [1]"
    assert [(c.number, c.chunk_id) for c in citations] == [(1, chunk.chunk_id)]
