"""Uniqueness and facet rules as lint findings (PLAN.md 4.6). Warnings, never hard failures."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.models import LintFinding, Section, SectionStatus
from app.synthesis.facets import FacetCatalog
from app.templates.schema import Template

_DEFINITION_RE = re.compile(
    r"(?m)^(?:Die |Der |Das |Ein |Eine )?[A-ZÄÖÜ][\wäöüß-]{2,40} (?:ist|sind) (?:ein|eine|der|die|das) "
)
_PERSON_HEADING_RE = re.compile(r"(?m)^#{3,5} [^\n]*\(\*\s*\d")
_RELEVANCE_RE = re.compile(
    r"\b(von großer Bedeutung|spielt eine (?:wichtige|zentrale) Rolle|ist (?:heute )?unverzichtbar)\b", re.IGNORECASE
)


def lint_sections(template: Template, sections: Sequence[Section], catalog: FacetCatalog) -> list[LintFinding]:
    findings: list[LintFinding] = []
    slots = {slot.id: slot for slot in template.slots}
    # The blocks the rules below speak of, as this template has them - sc26's numbers were wrong for any other
    # (audit 2026-09-27, AR-04)
    number = {slot.id: n for n, slot in enumerate(template.slots, 1)}
    glossary = any(slot.generator == "glossary" for slot in template.slots)
    actors = next((slot for slot in template.slots if slot.generator == "actors"), None)
    context = next((slot for slot in template.slots if slot.role == "context"), None)
    for section in sections:
        slot = slots.get(section.slot_id)
        if slot is None or section.status is SectionStatus.EMPTY:
            continue
        required = catalog.required_for(slot)
        for name in required:
            if not section.facets.get(name):
                findings.append(
                    LintFinding(
                        rule="facet-required", section_id=section.slot_id, message=f"Pflichtfacette „{name}“ fehlt"
                    )
                )
        allowed = set(catalog.allowed_for(slot))
        for name in section.facets:
            if allowed and name not in allowed:
                findings.append(
                    LintFinding(
                        rule="facet-not-allowed",
                        severity="info",
                        section_id=section.slot_id,
                        message=f"Facette „{name}“ ist in {slot.title} nicht deklariert",
                    )
                )
        defines = slot.role == "definition" or slot.slot == template.default_slot or slot.is_generated
        if glossary and not defines:
            hits = _DEFINITION_RE.findall(section.text)
            if len(hits) >= 2:
                findings.append(
                    LintFinding(
                        rule="definition-outside-glossary",
                        severity="info",
                        section_id=section.slot_id,
                        message=f"{len(hits)} Definitionssätze außerhalb des Glossars",
                    )
                )
        if actors is not None and slot.id != actors.id and _PERSON_HEADING_RE.search(section.text):
            findings.append(
                LintFinding(
                    rule="person-heading-outside-actors",
                    section_id=section.slot_id,
                    message=f"Personenname als Überschrift außerhalb von Baustein {number[actors.id]}",
                )
            )
        if context is not None and slot.id != context.id and _RELEVANCE_RE.search(section.text):
            findings.append(
                LintFinding(
                    rule="relevance-outside-context",
                    severity="info",
                    section_id=section.slot_id,
                    message=f"Relevanzaussage außerhalb von Baustein {number[context.id]}",
                )
            )
    return findings
