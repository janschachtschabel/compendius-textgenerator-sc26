"""A template holds only blocks its markers can carry and patterns that stay fast (audit 2026-09-28, AP-04).

The markers of a compendium need a block id without spaces or "-->" and a heading on one line: of four blocks with
the id "b 1", a title over two lines and an id with "-->" in it, parse_document read two, and existing_markdown then
replaced even reviewed blocks without a word. A heading pattern with nested quantifiers such as ^(\\w+\\s?)+$ took four
times as long for every two characters of a heading. Only admins save templates, but a stored one serves every
request that names it.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.templates.manager import TemplateManager
from app.templates.schema import MAX_SLOTS, Template, TemplateSlot

B = chr(92)


def slot(**fields: Any) -> dict[str, Any]:
    return {"id": "block_1", "slot": "fachinhalte", "title": "Fachinhalte", **fields}


@pytest.mark.parametrize(
    "fields",
    [
        {"id": "b 1"},
        {"id": "b1 -->"},
        {"slot": "fach inhalte"},
        {"title": "Zeile eins" + chr(10) + "Zeile zwei"},
        {"heading_patterns": ["^(" + B + "w+" + B + "s?)+$"]},
        {"heading_patterns": ["(a*)*b"]},
        {"heading_patterns": ["(?:x{1,5})+"]},
        {"description": "x" * 5000},
        {"search_queries": ["Optik"] * 100},
    ],
)
def test_a_block_its_markers_cannot_carry_or_a_slow_pattern_is_refused(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TemplateSlot(**slot(**fields))


def test_plain_patterns_and_bounded_repeats_stay_allowed() -> None:
    patterns = ["^Geschichte$", "(?:Aufbau|Struktur)", "(ab){2,3}", "^Bekannte " + B + "w+$", "(?i)^(Anwendung(en)?)$"]

    assert TemplateSlot(**slot(heading_patterns=patterns)).heading_patterns == patterns


def test_a_template_has_at_most_as_many_blocks_as_a_request_may_name() -> None:
    blocks = [slot(id=f"b{number}", slot=f"s{number}") for number in range(MAX_SLOTS + 1)]

    with pytest.raises(ValidationError):
        Template(id="gross", name="Groß", slots=blocks)


def test_the_built_in_templates_keep_within_the_bounds() -> None:
    manager = TemplateManager()

    for template_id in ("sc26", "standard"):
        template = manager.get(template_id)
        assert Template.model_validate(template.model_dump()) == template
