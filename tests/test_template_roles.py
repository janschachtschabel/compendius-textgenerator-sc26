"""What a block is for, said by the template instead of by the sc26 keys in the code (audit 2026-09-27, AR-04).

The rules knew the definition block as "themendefinition", the overview as "systematik", the actors as "akteure" and
the context as "gesellschaftlicher_kontext", and the preamble named the sources "Baustein 12" - true for sc26 only.
A block of another name lost the lead of the main article (0.0 instead of 2.0, the first paragraph to go when the
budgets cut), and the standard template, whose sources are block 6, read "Baustein 12".
"""

from __future__ import annotations

from typing import Any

from app.compendium.prepared import PreparedTopic
from app.compose.assembler import build_frontmatter
from app.domain.models import Section, SectionStatus
from app.domain.requests import GenerateRequest
from app.matching.policy import LEAD_SCORE, assign
from app.service import CompendiumService
from app.synthesis.facets import FacetCatalog
from app.synthesis.lint import lint_sections
from app.synthesis.qa_knowledge import knowledge_of_compendium
from app.templates.manager import TemplateManager
from app.templates.schema import Template, TemplateSlot
from tests.conftest import ROOT

PERSON = "#### Albert Einstein (* 1879 in Ulm)\nEr erklärte den photoelektrischen Effekt."
RELEVANCE = "Die Optik spielt eine zentrale Rolle in der Medizin."
DEFINITIONS = "Die Linse ist ein optisches Bauteil.\nDas Prisma ist ein Körper aus Glas."


def _renamed(template: Template, key: str, new_key: str, **update: Any) -> Template:
    data = template.model_dump()
    for slot in data["slots"]:
        if slot["slot"] == key:
            slot.update({"slot": new_key, **update})
    return Template.model_validate({**data, "id": "eigen", "builtin": False})


def test_a_definition_block_of_another_name_gets_the_lead(service: CompendiumService) -> None:
    prepared: PreparedTopic = service.prepare(GenerateRequest(topic="Optik", parts=["world"]))
    template = _renamed(prepared.template, "themendefinition", "einleitung", role="definition")
    lead = next(chunk for chunk in prepared.chunks if chunk.is_lead)

    result = assign(template, prepared.chunks, {}, prepared.sources_by_id)

    block = template.slot_by_key("einleitung")
    assert block is not None
    scored = {item.chunk.chunk_id: item for item in result.assigned[block.id]}
    assert scored[lead.chunk_id].score == LEAD_SCORE


def test_a_block_key_in_capitals_is_the_key_the_rules_know(service: CompendiumService) -> None:
    """KO-07 took "Praxis" into matcher=llm only: the roles, the lexicon, the facets and the actors compared the keys
    exactly, and a "Themendefinition" lost its role and the lead (0.0 instead of 2.0; audit 2026-09-28, KO-22)."""
    prepared: PreparedTopic = service.prepare(GenerateRequest(topic="Optik", parts=["world"]))
    data = prepared.template.model_dump()
    for slot in data["slots"]:
        slot.update({"slot": slot["slot"].capitalize(), "role": ""})
    default = data.get("default_slot")
    template = Template.model_validate(
        {**data, "id": "eigen", "builtin": False, "default_slot": default.upper() if default else None}
    )
    lead = next(chunk for chunk in prepared.chunks if chunk.is_lead)

    result = assign(template, prepared.chunks, {}, prepared.sources_by_id)

    block = template.slot_by_key("Themendefinition")
    assert block is not None and block.slot == "themendefinition" and block.role == "definition"
    scored = {item.chunk.chunk_id: item for item in result.assigned[block.id]}
    assert scored[lead.chunk_id].score == LEAD_SCORE
    assert template.default_slot == (default or None)


def test_a_template_without_roles_takes_them_from_the_keys() -> None:
    """A custom template written before roles, like a copy of sc26, keeps working as it did."""
    template = Template(
        id="x",
        name="x",
        slots=[
            TemplateSlot(id="a", slot="themendefinition", title="A"),
            TemplateSlot(id="b", slot="systematik", title="B"),
            TemplateSlot(id="c", slot="gesellschaftlicher_kontext", title="C"),
            TemplateSlot(id="d", slot="praxis", title="D"),
        ],
    )
    assert [slot.role for slot in template.slots] == ["definition", "systematik", "context", ""]


def test_a_template_that_names_its_roles_is_taken_at_its_word() -> None:
    template = Template(
        id="x",
        name="x",
        slots=[
            TemplateSlot(id="a", slot="einleitung", title="A", role="definition"),
            TemplateSlot(id="b", slot="systematik", title="B"),
        ],
    )
    assert [slot.role for slot in template.slots] == ["definition", ""]


def test_the_built_in_templates_name_their_roles() -> None:
    manager = TemplateManager()
    roles = {
        template_id: {slot.slot: slot.role for slot in manager.get(template_id).slots if slot.role}
        for template_id in ("sc26", "standard")
    }
    assert roles["sc26"] == {
        "themendefinition": "definition",
        "systematik": "systematik",
        "gesellschaftlicher_kontext": "context",
    }
    assert roles["standard"] == {"themendefinition": "definition", "gesellschaftlicher_kontext": "context"}


def _licence(template: Template) -> str:
    front = build_frontmatter(
        topic="Optik",
        resolution={},
        template=template,
        extraction="rule-based",
        generation="rule-based",
        generated_at="2026-09-28T00:00:00+00:00",
        zim_snapshot=[],
        matcher=None,
        parts=["world"],
    )
    licence: str = front["license"]
    return licence


def test_the_licence_note_names_the_sources_block_of_the_template() -> None:
    manager = TemplateManager()
    assert _licence(manager.get("sc26")).endswith("TULLU je Quelle in Baustein 12")
    assert _licence(manager.get("standard")).endswith("TULLU je Quelle in Baustein 6")
    without = Template(id="x", name="x", slots=[TemplateSlot(id="a", slot="praxis", title="A")])
    assert "TULLU" not in _licence(without)


def _findings(template_id: str, block: str, text: str) -> dict[str, str]:
    template = TemplateManager().get(template_id)
    slot = template.slot_by_key(block)
    assert slot is not None
    section = Section(slot_id=slot.id, slot_key=slot.slot, title=slot.title, text=text, status=SectionStatus.EXTRACTIVE)
    catalog = FacetCatalog.load(ROOT / "config" / "facets.yaml")
    return {finding.rule: finding.message for finding in lint_sections(template, [section], catalog)}


def test_the_lint_speaks_of_the_blocks_of_the_template() -> None:
    assert _findings("sc26", "praxis", PERSON)["person-heading-outside-actors"].endswith("Baustein 6")
    assert _findings("standard", "praxis", RELEVANCE)["relevance-outside-context"].endswith("Baustein 5")
    assert "definition-outside-glossary" in _findings("sc26", "praxis", DEFINITIONS)


def test_a_rule_about_a_block_the_template_lacks_stays_silent() -> None:
    """standard has neither actors nor glossary: a person heading or two definitions are nowhere out of place."""
    assert "person-heading-outside-actors" not in _findings("standard", "praxis", PERSON)
    assert "definition-outside-glossary" not in _findings("standard", "praxis", DEFINITIONS)


def test_the_glossary_and_the_actors_are_found_whatever_their_keys(service: CompendiumService) -> None:
    """/qa read them by the keys "glossar" and "akteure"; a template naming them otherwise gave it neither."""
    compendium = service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))
    renamed = compendium.model_copy(
        update={"sections": [s.model_copy(update={"slot_key": f"eigen_{s.slot_key}"}) for s in compendium.sections]}
    )
    made = knowledge_of_compendium(compendium)
    assert made.glossary and made.actors, "the sample compendium has both blocks, or this test proves nothing"
    assert knowledge_of_compendium(renamed) == made
