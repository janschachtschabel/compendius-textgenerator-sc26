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
import yaml
from pydantic import ValidationError

from app.templates.manager import TemplateManager
from app.templates.schema import (
    MAX_SLOTS,
    PATTERN_STEPS_MAX,
    TEMPLATE_PATTERN_STEPS_MAX,
    Template,
    TemplateSlot,
    pattern_steps,
)
from tests.conftest import ROOT

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


@pytest.mark.parametrize(
    "pattern",
    [
        "^(a|aa)+$",  # overlapping alternatives repeated without end
        "(?:.|..)*!",  # 31 characters of a heading 0.13 s, six times as long for every four more
        "(?:" + B + "w|" + B + "w" + B + "w)*!",
        ".*" * 12 + "!",  # twelve unbounded repeats in a row: 21.5 s on 24 characters
        "(?:a|aa)" * 30 + "$",  # overlapping alternatives in a row, without any repeat
        "^(?:a|aa){1,30}$",  # a bounded repeat of alternatives with a large maximum
    ],
)
def test_a_pattern_whose_work_grows_without_a_small_bound_is_refused(pattern: str) -> None:
    """A08: the check of AP-04 found only a repeat inside a repeat; each of these passed it (audit 2026-09-29)."""
    with pytest.raises(ValidationError):
        TemplateSlot(**slot(heading_patterns=[pattern]))


def test_patterns_as_the_shared_lexicon_writes_them_stay_allowed() -> None:
    """The hand-written patterns of config/heading_lexicon.yaml, some longer than a template's may be, show what a
    template's patterns look like: all of them together stay within the bound of one template."""
    raw = yaml.safe_load((ROOT / "config" / "heading_lexicon.yaml").read_text(encoding="utf-8"))
    shared = [*raw["exclude"], *raw["relations"], *(pattern for group in raw["slots"].values() for pattern in group)]
    steps = {pattern: pattern_steps(pattern) for pattern in shared}
    written = ["^" + B + "w+ " + B + "w+$", "Geschichte.*Optik", "^(Geschichte|Historie)( der " + B + "w+)?$"]

    assert all(step is not None and step <= PATTERN_STEPS_MAX for step in steps.values()), steps
    assert sum(step or 0 for step in steps.values()) <= TEMPLATE_PATTERN_STEPS_MAX
    assert TemplateSlot(**slot(heading_patterns=written)).heading_patterns == written


def test_the_patterns_of_all_blocks_together_stay_within_a_bound() -> None:
    """Every heading runs through the patterns of every block: patterns each within their bound still add up."""
    wide = "^" + B + "w+ " + B + "w+$"  # within the bound of one pattern
    blocks = [slot(id=f"b{number}", slot=f"s{number}", heading_patterns=[wide]) for number in range(4)]

    assert Template(id="t", name="t", slots=blocks[:3]).slots
    with pytest.raises(ValidationError, match="zusammen"):
        Template(id="t", name="t", slots=blocks)


def test_a_template_has_at_most_as_many_blocks_as_a_request_may_name() -> None:
    blocks = [slot(id=f"b{number}", slot=f"s{number}") for number in range(MAX_SLOTS + 1)]

    with pytest.raises(ValidationError):
        Template(id="gross", name="Groß", slots=blocks)


def test_the_built_in_templates_keep_within_the_bounds() -> None:
    manager = TemplateManager()

    for template_id in ("sc26", "standard"):
        template = manager.get(template_id)
        assert Template.model_validate(template.model_dump()) == template
