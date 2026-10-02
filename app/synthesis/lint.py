"""Uniqueness and facet rules as lint findings (PLAN.md 4.6). Warnings, never hard failures."""

from __future__ import annotations

import os
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


TOPIC_SCOPE = "topic-scope"
# Words of a topic that name no subject of their own: "Dichter aus dem Mittelalter" asks for poets and the Middle Ages
_FILLERS = frozenset(
    {"aus", "dem", "den", "der", "des", "die", "das", "im", "in", "ins", "am", "an", "auf", "bei", "für", "mit", "und"}
)
_WORD_RE = re.compile(r"[^\W\d_]+")


def topic_scope_finding(
    asked: str, article: str | None, *, normalized: str, covers: bool | None, method: str | None, about_topic: bool
) -> LintFinding | None:
    """A hint when the compendium treats another article than the topic as asked - a group without an article of
    its own or a topic with an aspect -, naming the profiles that write about the topic (M52: fit 4.2 to 5.0 for
    groups and aspects against at most 3.8). The heading names the topic as asked in every profile (D75); the hint
    says what a verbatim text prints under it.

    ``covers`` is the question N's word on whether its overview covers the topic (prompt topic_articles v2); without it
    (llm-free) the words of the ``normalized`` topic decide, one the article's title lacks - a level such as "in
    Klasse 7" is gone there, it is no aspect. A redirect (``method`` title to another title than ``normalized``) is
    the same topic for the archive, an article of the very name of the topic as asked is the topic, and a text the
    LLM wrote about the topic as asked (``about_topic``) needs no hint. Measured on the 94 gold queries of the
    article choice and the nine topics of M48 (M49)."""
    if article is None or about_topic or article.casefold() in (asked.casefold(), normalized.casefold()):
        return None  # the article of the topic's very name, also once a level or subject went (D12)
    if method == "title" and normalized.casefold() != article.casefold():  # a redirect
        return None
    wider = not covers if covers is not None else bool(_words_missing(normalized, article))
    if not wider:
        return None
    return LintFinding(
        rule=TOPIC_SCOPE,
        severity="info",
        message=(
            f"Das Kompendium behandelt den Artikel „{article}“, nicht genau das angefragte Thema „{asked}“. Ist es "
            "eine Gruppe oder ein Aspekt, schreiben die Profile best-coverage-generated und best-quality-generated "
            "zum angefragten Thema (M52)."
        ),
    )


def _words_missing(topic: str, article: str) -> list[str]:
    """The topic's words the article's title lacks, an inflected form counting as the word ("Edelgase", "Edelgas")."""
    title = [word.lower() for word in _WORD_RE.findall(article)]
    return [
        word
        for word in (w.lower() for w in _WORD_RE.findall(topic))
        if len(word) > 2 and word not in _FILLERS and not any(_same_stem(word, other) for other in title)
    ]


def _same_stem(a: str, b: str) -> bool:
    """One word, inflected ("Edelgase", "Edelgas") or part of a compound ("Kreislauf", "Wasserkreislauf")."""
    if a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)):
        return True
    shared = len(os.path.commonprefix([a, b]))
    return shared >= 4 and shared >= min(len(a), len(b)) - 2
