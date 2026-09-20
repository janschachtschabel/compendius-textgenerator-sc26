"""Markdown assembly (PLAN.md 4.6 notation, Anhang A)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

import yaml

from app.domain.models import Section, SectionStatus, SourceRef
from app.synthesis.facets import format_marker, format_visible
from app.templates.schema import Template

AI_DISCLOSURE = {  # by the generation switch actually used
    "rule-based": "Maschinell erstellter Text (regelbasiert-extraktiv) nach Art. 50 EU AI Act",
    "llm-fast": "Maschinell erstellter Text, Teile KI-generiert (Kennzeichnung je Abschnitt) nach Art. 50 EU AI Act",
    "llm": "KI-generierter Text auf Basis belegter Quellen (Kennzeichnung je Abschnitt) nach Art. 50 EU AI Act",
}
# enrichment=model-knowledge: the text carries sentences no source covers, so the disclosure has to say so
AI_ENRICHED_DISCLOSURE = (
    "KI-generierter Text auf Basis belegter Quellen, ergänzt um Modellwissen ohne Quellenbeleg "
    "(Kennzeichnung je Abschnitt und je Satz) nach Art. 50 EU AI Act"
)
# Rule-based writing from sentences the LLM chose (extraction=llm): the wording is the sources', the choice is not
AI_SELECTED_DISCLOSURE = (
    "Maschinell erstellter Text aus wörtlichen Quellenauszügen, Auswahl KI-gestützt (Kennzeichnung je Abschnitt) "
    "nach Art. 50 EU AI Act"
)


def section_marker(section: Section) -> str:
    digest = hashlib.sha256(section.text.encode("utf-8")).hexdigest()[:12]
    facets = format_marker(section.facets)
    facet_part = f' facets="{facets}"' if facets else ""
    return f"<!-- kompendium:section id={section.slot_id} status={section.status.value}{facet_part} hash={digest} -->"


EMPTY_SECTION_TEXT = (
    "*Für diesen Baustein lagen in den herangezogenen Quellen keine hinreichend passenden Abschnitte vor.*"
)


def build_frontmatter(
    *,
    topic: str,
    resolution: Mapping[str, Any],
    template: Template,
    extraction: str,
    generation: str,
    generated_at: str,
    enrichment: str = "sources-only",
    enriched_sentences: int = 0,
    zim_snapshot: Sequence[Mapping[str, Any]],
    matcher: str | None,
    parts: Sequence[str],
    extraction_requested: str | None = None,
    generation_requested: str | None = None,
    llm: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``extraction`` and ``generation`` are the switches actually used; ``*_requested`` appears only when a switch
    fell back to rule-based, and ``matcher`` only when part 1 was generated.

    ``enrichment`` is the mode the request was granted; ``enriched_sentences`` is what the text really carries.
    The disclosure follows the text: a permission the model did not use must not be declared as model knowledge.
    """
    if generation != "rule-based" and enrichment == "model-knowledge" and enriched_sentences:
        disclosure, review = AI_ENRICHED_DISCLOSURE, "ki-generiert"
    elif generation != "rule-based":
        disclosure, review = AI_DISCLOSURE.get(generation, AI_DISCLOSURE["llm"]), "ki-generiert"
    elif extraction == "llm":
        disclosure, review = AI_SELECTED_DISCLOSURE, "ki-ausgewählt"
    else:
        disclosure, review = AI_DISCLOSURE["rule-based"], "maschinell-extraktiv"
    frontmatter: dict[str, Any] = {
        "kompendium_version": 2,
        "topic": topic,
        "topic_resolution": dict(resolution),
        "template": {"id": template.id, "version": template.version},
        "parts": list(parts),
        "generated_at": generated_at,
        "extraction": extraction,
        "generation": generation,
        "enrichment": enrichment,
        **({"matcher": matcher} if matcher is not None else {}),
        "ai_disclosure": disclosure,
        "review": {"status": review, "interval_months": 12},
        "sources_snapshot": [dict(s) for s in zim_snapshot],
    }
    if "world" in parts:  # the licence note speaks about part 1 only
        frontmatter["license"] = (
            "Teil 1 enthält Inhalte aus Kiwix-Archiven freier Wissensprojekte (CC BY-SA 4.0); "
            "TULLU je Quelle in Baustein 12"
        )
    if extraction_requested is not None and extraction_requested != extraction:
        frontmatter["extraction_requested"] = extraction_requested
    if generation_requested is not None and generation_requested != generation:
        frontmatter["generation_requested"] = generation_requested
    if llm is not None:
        frontmatter["llm"] = dict(llm)
    return frontmatter


def render_markdown(
    *,
    topic: str,
    frontmatter: Mapping[str, Any],
    template: Template,
    sections: Sequence[Section],
    sources: Sequence[SourceRef],
    facets_visible: bool,
    extra_parts: Sequence[str] = (),
    include_world: bool = True,
) -> str:
    """Render frontmatter, title and part 1 with one marker per section; ``extra_parts`` follow as given.

    ``include_world`` is off when the request did not ask for part 1.
    """
    lines: list[str] = [
        "---",
        yaml.safe_dump(dict(frontmatter), allow_unicode=True, sort_keys=False).rstrip(),
        "---",
        "",
    ]
    lines.append(f"# Kompendium: {topic}")
    lines.append("")
    if include_world:
        lines.append("## Teil 1 · Weltwissen")
        lines.append("")
        for section in sections:
            if section.status is SectionStatus.EMPTY and template.empty_slot_policy == "omit":
                continue
            title = section.title
            if facets_visible and section.facets:
                title = f"{title} {format_visible(section.facets)}"
            lines.append(f"### {title}")
            lines.append(section_marker(section))
            lines.append("")
            if section.status is SectionStatus.EMPTY:
                lines.append(EMPTY_SECTION_TEXT)
            else:
                lines.append(section.text)
            lines.append("")
        if not sources:
            lines.append("*Keine Quellen gefunden.*")
    for part in extra_parts:
        lines.extend(["", part.rstrip()])
    return "\n".join(lines).rstrip() + "\n"
