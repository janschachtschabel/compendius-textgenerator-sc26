"""Markdown assembly (PLAN.md 4.6 notation, Anhang A)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import yaml

from app.domain.models import Section, SectionStatus, SourceRef
from app.synthesis.facets import format_marker, format_visible
from app.synthesis.safe_markdown import plain_label
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
# Rule-based writing from sentences or paragraphs an LLM chose (extraction=llm, matcher=llm): the wording is the
# sources', the choice is not
AI_SELECTED_DISCLOSURE = (
    "Maschinell erstellter Text aus wörtlichen Quellenauszügen, Auswahl KI-gestützt (Kennzeichnung je Abschnitt) "
    "nach Art. 50 EU AI Act"
)


def section_marker(section: Section) -> str:
    digest = hashlib.sha256(section.text.encode("utf-8")).hexdigest()[:12]
    facets = format_marker(section.facets)
    facet_part = f' facets="{facets}"' if facets else ""
    return f"<!-- kompendium:section id={section.slot_id} status={section.status.value}{facet_part} hash={digest} -->"


# A value of the frontmatter may come from a source - a collection's title is the topic - and a renderer that does not
# know frontmatter reads the block as markdown. Such strings are written double-quoted with "<", ">", "&" and the
# brackets as escapes: YAML reads the value back unchanged, a renderer sees no tag and no link (audit 2026-09-28,
# SE-16). Only inside the quotes: YAML itself writes an empty list as []
_INERT = {"<": "\\u003C", ">": "\\u003E", "&": "\\u0026", "[": "\\u005B", "]": "\\u005D"}
_QUOTED = re.compile(r'"(?:[^"\\]|\\[\s\S])*"')  # an escape may end a folded line


class _InertDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True  # no anchors: "&" then only stands inside quoted strings


def _string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = '"' if any(sign in value for sign in _INERT) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_InertDumper.add_representer(str, _string)


def inert_yaml(data: Mapping[str, Any]) -> str:
    """``data`` as YAML in which no markdown renderer finds a tag."""
    text = yaml.dump(dict(data), Dumper=_InertDumper, allow_unicode=True, sort_keys=False).rstrip()
    return _QUOTED.sub(lambda quoted: "".join(_INERT.get(sign, sign) for sign in quoted.group(0)), text)


EMPTY_SECTION_TEXT = (
    "*Für diesen Baustein lagen in den herangezogenen Quellen keine hinreichend passenden Abschnitte vor.*"
)


@dataclass(frozen=True)
class Switches:
    """How part 1 came about, for the frontmatter and its disclosure: eight of the fifteen parameters of
    build_frontmatter (audit 2026-09-28, WA-06).

    ``extraction``, ``generation`` and ``matcher`` are what was actually used; ``*_requested`` appears only when a
    switch or matcher=llm fell back to the rules, and ``matcher`` only when part 1 was generated. ``enrichment`` is the
    mode the request was granted, ``enriched_sentences`` what the text really carries: the disclosure follows the
    text, and a permission the model did not use must not be declared as model knowledge.

    ``kept`` names the blocks a regeneration kept from an earlier compendium with their status, and
    ``kept_model_knowledge`` the sentences of model knowledge those of them carry that no editor reviewed: the
    disclosure follows the whole text, not only what this run wrote (audit 2026-09-29, A04).
    """

    extraction: str = "rule-based"
    generation: str = "rule-based"
    enrichment: str = "sources-only"
    enriched_sentences: int = 0
    matcher: str | None = None
    extraction_requested: str | None = None
    generation_requested: str | None = None
    matcher_requested: str | None = None
    kept: Mapping[str, SectionStatus] = field(default_factory=dict)
    kept_model_knowledge: int = 0


def build_frontmatter(
    *,
    topic: str,
    resolution: Mapping[str, Any],
    template: Template,
    switches: Switches,
    generated_at: str,
    zim_snapshot: Sequence[Mapping[str, Any]],
    parts: Sequence[str],
    llm: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The YAML frontmatter of a compendium: topic and its resolution, template, parts, how part 1 came about
    (``switches``) with its disclosure, the archives it read and what the LLM did (``llm``)."""
    extraction, generation, enrichment, matcher = (
        switches.extraction,
        switches.generation,
        switches.enrichment,
        switches.matcher,
    )
    enriched_sentences = switches.enriched_sentences
    # A kept block counts with the status it carries; a reviewed one stands under editorial responsibility (Art. 50(4)
    # EU AI Act), whoever wrote it first
    kept = set(switches.kept.values())
    if (generation != "rule-based" and enrichment == "model-knowledge" and enriched_sentences) or (
        switches.kept_model_knowledge
    ):
        disclosure, review = AI_ENRICHED_DISCLOSURE, "ki-generiert"
    elif generation != "rule-based":
        disclosure, review = AI_DISCLOSURE.get(generation, AI_DISCLOSURE["llm"]), "ki-generiert"
    elif SectionStatus.LLM in kept:
        disclosure, review = AI_DISCLOSURE["llm"], "ki-generiert"
    elif extraction == "llm" or matcher == "llm" or SectionStatus.LLM_SELECTED in kept:
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
    if switches.kept:  # blocks of an earlier compendium: the switches above say what this run did
        frontmatter["kept_sections"] = {slot_id: status.value for slot_id, status in switches.kept.items()}
    if "world" in parts:  # the licence note speaks about part 1 only
        # the number of the template's sources block: 12 in sc26, 6 in standard (audit 2026-09-27, AR-04)
        number = next((n for n, slot in enumerate(template.slots, 1) if slot.generator == "sources"), None)
        per_source = f"; TULLU je Quelle in Baustein {number}" if number is not None else ""
        frontmatter["license"] = (
            "Teil 1 enthält Inhalte aus Kiwix-Archiven freier Wissensprojekte (CC BY-SA 4.0)" + per_source
        )
    if switches.extraction_requested is not None and switches.extraction_requested != extraction:
        frontmatter["extraction_requested"] = switches.extraction_requested
    if switches.generation_requested is not None and switches.generation_requested != generation:
        frontmatter["generation_requested"] = switches.generation_requested
    if switches.matcher_requested is not None and switches.matcher_requested != matcher:
        frontmatter["matcher_requested"] = switches.matcher_requested
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
    include_frontmatter: bool = True,
) -> str:
    """Render frontmatter, title and part 1 with one marker per section; ``extra_parts`` follow as given.

    ``include_world`` is off when the request did not ask for part 1. Without ``include_frontmatter``
    the text starts at the heading: the caller renders the document elsewhere and does not want a YAML
    block in front of it. The data is not lost - it stays in the ``frontmatter`` field of the answer.
    """
    lines: list[str] = []
    if include_frontmatter:
        lines += [
            "---",
            inert_yaml(frontmatter),
            "---",
            "",
        ]
    lines.append(f"# Kompendium: {plain_label(topic)}")
    lines.append("")
    if include_world:
        lines.append("## Teil 1 · Weltwissen")
        lines.append("")
        for section in sections:
            if section.status is SectionStatus.EMPTY and template.empty_slot_policy == "omit":
                continue
            title = plain_label(section.title)
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
