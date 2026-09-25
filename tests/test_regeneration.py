"""Partial regeneration (PLAN.md 4.6): a reviewed block survives, the rest is made anew."""

from __future__ import annotations

import re

import pytest

from app.compose.regeneration import UnknownSectionsError
from app.domain.requests import GenerateRequest
from app.service import CompendiumService

SECTION_RE = re.compile(
    r"### (?P<title>[^\n]+)\n<!-- kompendium:section id=(?P<slot>\S+) status=(?P<status>[^ ]+)(?P<rest>[^>]*)-->\n\n"
    r"(?P<text>.*?)(?=\n### |\n## |\Z)",
    re.DOTALL,
)


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
