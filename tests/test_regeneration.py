"""Partial regeneration (PLAN.md 4.6): a reviewed block survives, the rest is made anew."""

from __future__ import annotations

import re

import pytest

from app.compose.regeneration import (
    UnknownSectionsError,
    UnreadableDocumentError,
    _citation_rows,
    parse_document,
)
from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.synthesis.citations import marker_numbers

SECTION_RE = re.compile(
    r"### (?P<title>[^\n]+)\n<!-- kompendium:section id=(?P<slot>\S+) status=(?P<status>[^ ]+)(?P<rest>[^>]*)-->\n\n"
    r"(?P<text>.*?)(?=\n### |\n## |\Z)",
    re.DOTALL,
)


ESCAPED_BRACKET = chr(92) + "["  # spelled out: tools on the way turn escapes in test text into other signs


def blocks(markdown: str) -> dict[str, str]:
    """Slot id -> the text of its block, as it stands in the document."""
    return {match.group("slot"): match.group("text").rstrip() for match in SECTION_RE.finditer(markdown)}


def mark_reviewed(markdown: str, slot_id: str) -> str:
    """What an editor's tool does: set the status of one block to ``redaktionell-geprüft``."""
    return re.sub(rf"(<!-- kompendium:section id={slot_id} status=)[^ ]+", r"\1redaktionell-geprüft", markdown, count=1)


def test_a_reviewed_block_survives_a_regeneration_word_for_word(service: CompendiumService) -> None:
    first = service.generate(GenerateRequest(topic="Optik", parts=["world"], target_length=8000))
    reviewed = mark_reviewed(first.markdown, "sc26_3")
    second = service.generate(
        GenerateRequest(topic="Optik", parts=["world"], target_length=2000, existing_markdown=reviewed)
    )
    assert blocks(second.markdown)["sc26_3"] == blocks(reviewed)["sc26_3"]
    kept = next(section for section in second.sections if section.slot_id == "sc26_3")
    assert kept.status.value == "redaktionell-geprüft"
    numbers = [citation.number for section in second.sections for citation in section.citations]
    # The kept block keeps its numbers, the new ones count on from the highest: unique, but no longer ascending
    assert len(numbers) == len(set(numbers))
    assert all(f"| [{number}] |" in second.markdown for number in numbers), "every number has a row in the table"


def test_regenerate_sections_names_the_blocks_that_change(service: CompendiumService) -> None:
    first = service.generate(GenerateRequest(topic="Optik", parts=["world"], target_length=8000))
    second = service.generate(
        GenerateRequest(
            topic="Optik",
            parts=["world"],
            target_length=2000,
            existing_markdown=first.markdown,
            regenerate_sections=["sc26_3"],
        )
    )
    before, after = blocks(first.markdown), blocks(second.markdown)
    content = [slot for slot in before if slot not in {"sc26_3", "sc26_6", "sc26_12", "sc26_13"}]
    assert content and all(before[slot] == after.get(slot) for slot in content)  # only the named block changed
    assert before["sc26_3"] != after["sc26_3"]
    # Blocks the earlier document left out (empty ones) have nothing to keep and are made anew as well
    assert "sc26_3" in second.audit.regenerated
    assert not set(content) & set(second.audit.regenerated)


def test_a_name_that_is_no_block_of_the_template_is_refused(service: CompendiumService) -> None:
    """It used to change nothing, without a word; a slot key is not the id either (review of 2026-09-25)."""
    request = GenerateRequest(
        topic="Optik", existing_markdown="# Optik", regenerate_sections=["sc26_3", "themendefinition", "sc26_99"]
    )
    with pytest.raises(UnknownSectionsError) as refused:
        service.generate(request)
    assert refused.value.unknown == ["themendefinition", "sc26_99"]
    assert "sc26_1 (themendefinition)" in str(refused.value) and "sc26_13" in str(refused.value)


def test_without_a_previous_text_everything_is_new(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"]))
    assert result.audit.regenerated == []


MERKUR = "https://de.wikipedia.org/wiki/Merkur_(Planet)"


def document(rows: list[str]) -> str:
    """A compendium in the shape the service writes: one reviewed block citing [1] and [2], then the table."""
    return "\n".join(
        [
            "## Teil 1",
            "",
            "### Aufbau",
            "<!-- kompendium:section id=sc26_3 status=redaktionell-geprüft hash=0a1b -->",
            "",
            "Der Merkur ist der sonnennächste Planet. [1] Licht wird an Linsen gebrochen. [2]",
            "",
            "### Quellen",
            "<!-- kompendium:section id=sc26_12 status=generiert hash=0c2d -->",
            "",
            "| Beleg | Quelle | Abschnitt | Textauszug |",
            "| :---: | :--- | :--- | :--- |",
            *rows,
        ]
    )


def test_a_row_whose_link_holds_parentheses_is_read() -> None:
    """url_for leaves parentheses unencoded, and many titles carry a qualifier (audit 2026-09-27, KO-02)."""
    parsed = parse_document(
        document(
            [
                f"| [1] | [Merkur (Planet)]({MERKUR}) | Aufbau | Der Merkur ist der sonnennächste Planet. |",
                "| [2] | [Optik](https://de.wikipedia.org/wiki/Optik) | Brechung | Licht wird an Linsen gebrochen. |",
            ]
        )
    )

    citations = {citation.number: citation for citation in parsed["sc26_3"].citations}
    assert citations[1].source_url == MERKUR
    assert citations[1].source_title == "Merkur (Planet)"
    assert citations[1].section_heading == "Aufbau"
    assert citations[2].source_url == "https://de.wikipedia.org/wiki/Optik"


def test_a_number_with_thousands_of_digits_is_no_row() -> None:
    # Python refuses to read a number of more than 4,300 digits; the row pattern used to hand it such a number
    parsed = parse_document(
        document(["| [" + "9" * 5000 + "] | [Optik](https://de.wikipedia.org/wiki/Optik) | a | b |"])
    )

    assert parsed["sc26_3"].citations == []


def test_the_rows_of_a_kept_block_survive_with_links_in_parentheses(service: CompendiumService) -> None:
    first = service.generate(GenerateRequest(topic="Optik", parts=["world"], target_length=8000))
    reviewed = mark_reviewed(first.markdown, "sc26_3")
    kept = marker_numbers(blocks(reviewed)["sc26_3"])
    assert kept
    # Every source the kept block cites now has a qualifier in its link, as "Merkur_(Planet)" has
    lines = reviewed.splitlines()
    for index, line in enumerate(lines):
        if any(line.startswith(f"| [{number}] | [") for number in kept):
            lines[index] = re.sub(r"\]\((https://[^ ]*?)\) \|", r"](\1_(Planet)) |", line, count=1)
    rewritten = "\n".join(lines)
    assert rewritten.count("_(Planet)) |") == len(kept)

    second = service.generate(
        GenerateRequest(topic="Optik", parts=["world"], target_length=2000, existing_markdown=rewritten)
    )

    # the sources block writes an address with parentheses in angle brackets now (audit 2026-09-28, SE-16): the
    # row keeps its title, address, heading and snippet, not its spelling
    before, after = _citation_rows(rewritten), _citation_rows(second.markdown)
    for number in kept:
        assert number in after, f"the row of [{number}] is lost"
        assert after[number] == before[number]
        assert after[number].source_url.endswith("_(Planet)")
    new = {c.number for section in second.sections if section.slot_id != "sc26_3" for c in section.citations}
    assert not new & set(kept), "a new block took a number the kept block still cites"


def test_the_rows_of_a_kept_block_stay_word_for_word_over_two_regenerations(service: CompendiumService) -> None:
    """The table escapes titles and snippets, and its rows are read back as typed; an escape read as text would be
    escaped again at every regeneration and the backslashes would pile up (audit 2026-09-28, SE-16)."""
    first = service.generate(GenerateRequest(topic="Optik", parts=["world"], target_length=8000))
    reviewed = mark_reviewed(first.markdown, "sc26_1")
    kept = marker_numbers(blocks(reviewed)["sc26_1"])
    second = service.generate(
        GenerateRequest(topic="Optik", parts=["world"], target_length=2000, existing_markdown=reviewed)
    )
    third = service.generate(
        GenerateRequest(topic="Optik", parts=["world"], target_length=2000, existing_markdown=second.markdown)
    )

    def rows(markdown: str) -> list[str]:
        return [line for line in markdown.splitlines() for n in kept if line.startswith(f"| [{n}] |")]

    assert rows(first.markdown) and rows(first.markdown) == rows(second.markdown) == rows(third.markdown)
    assert any(ESCAPED_BRACKET in row for row in rows(first.markdown))  # the lead of Optik quotes "[τέχνη]"


def test_new_blocks_count_on_past_every_marker_of_a_kept_block(service: CompendiumService) -> None:
    first = service.generate(GenerateRequest(topic="Optik", parts=["world"], target_length=8000))
    reviewed = mark_reviewed(first.markdown, "sc26_3")
    kept = marker_numbers(blocks(reviewed)["sc26_3"])
    # The rows of those numbers are gone, as when a tool rewrote the table; the markers still hold them
    stripped = "\n".join(
        line for line in reviewed.splitlines() if not any(line.startswith(f"| [{number}] |") for number in kept)
    )

    second = service.generate(
        GenerateRequest(topic="Optik", parts=["world"], target_length=2000, existing_markdown=stripped)
    )

    new = {c.number for section in second.sections if section.slot_id != "sc26_3" for c in section.citations}
    assert kept and new
    assert min(new) > max(kept)


LF, CR = chr(10), chr(13)  # spelled out: tools on the way turn escapes in test text into other signs


def test_a_reviewed_block_sent_with_windows_line_ends_is_kept(service: CompendiumService) -> None:
    """A text area sends CRLF; the markers were read with LF only, and every block was made anew, the reviewed one
    as well, with its status gone (audit 2026-09-29, A01)."""
    first = service.generate(GenerateRequest(topic="Optik", parts=["world"], target_length=8000))
    reviewed = mark_reviewed(first.markdown, "sc26_3")

    second = service.generate(
        GenerateRequest(
            topic="Optik", parts=["world"], target_length=2000, existing_markdown=reviewed.replace(LF, CR + LF)
        )
    )

    kept = next(section for section in second.sections if section.slot_id == "sc26_3")
    assert kept.status.value == "redaktionell-geprüft"
    assert kept.text == blocks(reviewed)["sc26_3"]
    assert "sc26_3" not in second.audit.regenerated


def test_a_subheading_an_editor_added_stays_in_its_reviewed_block(service: CompendiumService) -> None:
    """A block ended at the next "### " line: the text after an editor's own subheading was lost while the block
    still counted as kept (audit 2026-09-29, A01)."""
    first = service.generate(GenerateRequest(topic="Optik", parts=["world"], target_length=8000))
    reviewed = mark_reviewed(first.markdown, "sc26_3")
    original = blocks(reviewed)["sc26_3"]
    addition = LF.join(["", "", "### Ergänzung der Redaktion", "", "Ein Satz der Redaktion."])
    edited = reviewed.replace(original, original + addition, 1)

    second = service.generate(
        GenerateRequest(topic="Optik", parts=["world"], target_length=2000, existing_markdown=edited)
    )

    kept = next(section for section in second.sections if section.slot_id == "sc26_3")
    assert kept.text == original + addition
    assert original + addition in second.markdown


def test_an_earlier_marker_with_a_quote_in_a_facet_value_is_read() -> None:
    """Markers written before 2026-09-29 held a quote of a value as typed (audit 2026-09-29, A01)."""
    marker = '<!-- kompendium:section id=sc26_3 status=redaktionell-geprüft facets="Zitat=Zitat "Optik"" hash=0a1b -->'

    parsed = parse_document(LF.join(["### Aufbau", marker, "", "Geprüfter Text.", ""]))

    assert parsed["sc26_3"].facets == {"Zitat": ['Zitat "Optik"']}
    assert parsed["sc26_3"].text == "Geprüfter Text."


def test_a_marker_the_parser_cannot_read_is_refused() -> None:
    """A marker without its hash, or without the heading above it, kept nothing of its block, and the block was made
    anew without a word; now the request is refused and names the marker (audit 2026-09-29, A01)."""
    no_hash = "<!-- kompendium:section id=sc26_3 status=redaktionell-geprüft -->"
    headless = "<!-- kompendium:section id=sc26_4 status=redaktionell-geprüft hash=0a1b -->"
    markdown = LF.join(["## Teil 1", "", "### Aufbau", no_hash, "", "Text.", "", headless, "", "Mehr."])

    with pytest.raises(UnreadableDocumentError) as refused:
        parse_document(markdown)

    assert "id=sc26_3" in str(refused.value) and "id=sc26_4" in str(refused.value)


def test_a_block_that_stands_twice_is_refused() -> None:
    marker = "<!-- kompendium:section id=sc26_3 status=redaktionell-geprüft hash=0a1b -->"
    markdown = LF.join(["### Aufbau", marker, "", "Erste Fassung.", "", "### Aufbau", marker, "", "Zweite Fassung."])

    with pytest.raises(UnreadableDocumentError) as refused:
        parse_document(markdown)

    assert "sc26_3" in str(refused.value)


def test_a_broken_marker_refuses_the_whole_request(service: CompendiumService) -> None:
    broken = LF.join(["### Aufbau", "<!-- kompendium:section id=sc26_3 status=redaktionell-geprüft -->", "", "Text."])

    with pytest.raises(UnreadableDocumentError):
        service.generate(GenerateRequest(topic="Optik", parts=["world"], existing_markdown=broken))
