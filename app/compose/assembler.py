"""Markdown assembly (PLAN.md 4.6 notation, Anhang A)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

import yaml

from app.domain.models import Section, SectionStatus, SourceRef
from app.synthesis.facets import format_marker, format_visible
from app.templates.schema import Template

AI_DISCLOSURE = {
    "rule-based": "Maschinell erstellter Text (regelbasiert-extraktiv) nach Art. 50 EU AI Act",
    "hybrid-fast": "Maschinell erstellter Text, Teile KI-generiert (Kennzeichnung je Abschnitt) nach Art. 50 EU AI Act",
    "hybrid-quality": (
        "KI-generierter Text auf Basis belegter Quellen (Kennzeichnung je Abschnitt) nach Art. 50 EU AI Act"
    ),
}


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
    mode: str,
    generated_at: str,
    zim_snapshot: Sequence[Mapping[str, Any]],
    matcher: str | None,
    parts: Sequence[str],
    mode_requested: str | None = None,
    llm: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``mode`` is the mode actually used; ``mode_requested`` appears only when a hybrid request fell back, and
    ``matcher`` only when part 1 was generated."""
    frontmatter: dict[str, Any] = {
        "kompendium_version": 2,
        "topic": topic,
        "topic_resolution": dict(resolution),
        "template": {"id": template.id, "version": template.version},
        "parts": list(parts),
        "generated_at": generated_at,
        "mode": mode,
        **({"matcher": matcher} if matcher is not None else {}),
        "ai_disclosure": AI_DISCLOSURE.get(mode, AI_DISCLOSURE["rule-based"]),
        "review": {"status": "maschinell-extraktiv" if mode == "rule-based" else "ki-generiert", "interval_months": 12},
        "sources_snapshot": [dict(s) for s in zim_snapshot],
    }
    if "world" in parts:  # the licence note speaks about part 1 only
        frontmatter["license"] = (
            "Teil 1 enthält Inhalte aus Kiwix-Archiven freier Wissensprojekte (CC BY-SA 4.0); "
            "TULLU je Quelle in Baustein 12"
        )
    if mode_requested is not None and mode_requested != mode:
        frontmatter["mode_requested"] = mode_requested
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
