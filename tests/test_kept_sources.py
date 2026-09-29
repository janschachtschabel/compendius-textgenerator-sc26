"""The sources of an earlier compendium that only its kept blocks cite (PLAN.md 4.6; audit 2026-09-29, A04, C-02)."""

from __future__ import annotations

import time

from app.compose.kept_sources import attribute, read_sources
from app.compose.regeneration import PreservedSection
from app.domain.models import Citation, SectionStatus, Source
from app.synthesis.sources_section import build_sources_section

LINSE = Source(
    source_id="wikipedia:Linse (Optik)",
    project="wikipedia",
    title="Linse (Optik)",
    url="https://de.wikipedia.org/wiki/Linse_(Optik)",
    zim_file="wikipedia_de_sample_2026-01.zim",
    zim_date="2026-01",
    entry_path="A/Linse_(Optik)",
)
MATERIAL = Source(
    source_id="wlo:0f0e",
    project="wlo_material",
    title='Arbeitsblatt "Licht" [1] · Teil 2',
    url="https://example.org/blatt?a=b",
    license="CC BY 4.0",
    authors=["Anna Beispiel", "Ben Muster"],
)


def cite(number: int, source: Source) -> Citation:
    return Citation(
        number=number,
        source_id="",
        chunk_id="",
        source_title=source.title,
        source_url=source.url,
        section_heading="Aufbau",
        snippet="…",
    )


def test_an_entry_of_the_sources_block_reads_back_as_the_source_it_was_written_from() -> None:
    block = build_sources_section([LINSE, MATERIAL], [], facets_visible=False)

    read = {source.title: source for source in read_sources(block)}

    for original in (LINSE, MATERIAL):
        got = read[original.title]
        assert (got.project, got.url, got.license, got.authors) == (
            original.project,
            original.url,
            original.license,
            original.authors,
        )
        assert (got.zim_file, got.zim_date, got.entry_path) == (
            original.zim_file,
            original.zim_date,
            original.entry_path,
        )
        assert got.source_id.startswith("kept:")
    assert build_sources_section(list(read.values()), [], facets_visible=False) == block, "written again word for word"


def test_a_citation_of_a_kept_block_finds_its_source() -> None:
    """In the new corpus when it is there, else in the entry the earlier document wrote; without either it counts as
    unattributed, as does a marker without its row in the citation table."""
    earlier = build_sources_section([LINSE, MATERIAL], [], facets_visible=False)
    kept = {
        "sc26_3": PreservedSection(
            slot_id="sc26_3",
            status=SectionStatus.REVIEWED,
            text="Eine Linse bricht Licht. [1] Ein Blatt dazu. [2] Ein Satz ohne Zeile. [7]",
            citations=[cite(1, LINSE), cite(2, MATERIAL)],
        ),
        "sc26_4": PreservedSection(
            slot_id="sc26_4",
            status=SectionStatus.REVIEWED,
            text="Nirgends belegt. [5]",
            citations=[cite(5, Source(source_id="x", project="wikipedia", title="Prisma", url="https://e.x/Prisma"))],
        ),
    }
    current = [LINSE]

    found = attribute(kept, earlier, current)

    ids = {citation.number: citation.source_id for block in found.kept.values() for citation in block.citations}
    assert ids[1] == LINSE.source_id, "the new corpus has it"
    assert [source.title for source in found.carried] == [MATERIAL.title]
    assert ids[2] == found.carried[0].source_id
    assert found.unattributed == [5, 7]


def test_a_hostile_entry_is_read_in_linear_time() -> None:
    line = "  - TULLU: Titel „" + " · Urheber " * 100_000 + "“"
    block = "\n".join(["- **x**", line, "  - Archiv: " + "`" * 200_000])

    started = time.perf_counter()
    read_sources(block)

    assert time.perf_counter() - started < 1.0
