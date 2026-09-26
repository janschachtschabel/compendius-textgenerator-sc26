"""Part 2 rendering (PLAN.md 5.4): coverage note, state x level table, grouped entries with markers.

Structure: Bildungsstufe -> Bundesland -> Lehrplan (school type, grade) -> Lernbereich -> competencies
and contents as quotations with a link to the ``lp`` resource. Every group carries a marker so the
paragraphs can be parsed out later; visible facets only when requested. Levels not asserted in the
data are marked as derived. The provenance statistics go to the audit, not into the text.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.sources.lehrplan.matcher import CurriculumMatch, MatchResult
from app.sources.lehrplan.stufen import OHNE_KLASSE, OHNE_STUFE, PRIMAR, SEK_I, SEK_II, STUFEN_ORDER, grades_in
from app.sources.lehrplan.vocab import ROLE_INHALT, ROLE_KOMPETENZ, ROLE_THEMENBEREICH, bundesland_by_code
from app.synthesis.facets import END_MARKER, format_marker, format_visible

PART_HEADING = "## Teil 2 · Lehrplanbezüge"
FACET_STUFE = {PRIMAR: "Primar", SEK_I: "Sek I", SEK_II: "Sek II"}
ROLE_NAMES = {ROLE_THEMENBEREICH: "Themenbereich", ROLE_KOMPETENZ: "Kompetenz", ROLE_INHALT: "Inhalt"}
MISSING_CACHE_TEXT = (
    "*Der lokale Lehrplan-Cache ist nicht vorhanden. Lehrplanbezüge erscheinen, sobald der Harvest-Job "
    "(`compendium lehrplan harvest`) die MEM-Lehrpläne einmal vollständig abgezogen hat; zur "
    "Inferenzzeit wird nicht auf MEM zugegriffen.*"
)
UNREADABLE_CACHE_TEXT = (
    "*Der lokale Lehrplan-Cache ist nicht lesbar (beschädigt oder von einer anderen Version). Lehrplanbezüge "
    "erscheinen wieder, sobald der Harvest-Job (`compendium lehrplan harvest --force`) ihn neu aufgebaut hat; "
    "zur Inferenzzeit wird nicht auf MEM zugegriffen.*"
)


@dataclass(frozen=True)
class RenderOptions:
    """Part 2 renders every match by default (compendia may be long, decision D23); caps are opt-in."""

    max_groups_per_land: int | None = None
    max_items_per_group: int | None = None
    facets_visible: bool = False


@dataclass
class _Group:
    stufe: str
    land_code: str
    lehrplan_iri: str
    bereich: str
    lead: CurriculumMatch
    items: list[CurriculumMatch]


def render_missing_cache() -> str:
    return f"{PART_HEADING}\n\n{MISSING_CACHE_TEXT}\n"


def render_unreadable_cache() -> str:
    return f"{PART_HEADING}\n\n{UNREADABLE_CACHE_TEXT}\n"


def coverage(meta: Mapping[str, str]) -> dict[str, Any]:
    """Which states the cache covers, when it was harvested and how many curricula it holds."""
    counts: dict[str, int] = json.loads(meta.get("counts") or "{}")
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    names = [bundesland_by_code(code).name for code, _count in ordered if code]
    return {
        "states": names,
        "harvested_at": (meta.get("harvested_at") or "")[:10],
        "lehrplaene_total": sum(counts.values()),
    }


def _join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " und " + names[-1]


def _coverage_sentence(info: Mapping[str, Any]) -> str:
    states = _join_names(list(info["states"])) or "kein Bundesland"
    stand = f", Stand {info['harvested_at']}" if info["harvested_at"] else ""
    return (
        f"Lehrplanbezüge liegen strukturiert für {states} vor (MEM-Triplestore der FWU{stand}; "
        f"{info['lehrplaene_total']} Lehrpläne). Die Abdeckung wächst mit den Veröffentlichungen von MEM."
    )


def _bereich(match: CurriculumMatch) -> str:
    if ROLE_THEMENBEREICH in match.hit.rollen:
        return match.hit.label
    return match.hit.parent_label or match.hit.lehrplan.label


def _groups(result: MatchResult) -> list[_Group]:
    grouped: dict[tuple[str, str, str, str], _Group] = {}
    for match in result.matches:
        key = (match.schulstufe.value, match.hit.lehrplan.bundesland_code, match.hit.lehrplan.iri, _bereich(match))
        group = grouped.get(key)
        if group is None:
            group = grouped[key] = _Group(*key, lead=match, items=[])
        if not (ROLE_THEMENBEREICH in match.hit.rollen and match.hit.label == group.bereich):
            group.items.append(match)
    return list(grouped.values())


def _marker(group: _Group) -> str:
    lehrplan = group.lead.hit.lehrplan
    facets: dict[str, list[str]] = {"Bundesland": [lehrplan.bundesland]}
    if group.stufe in FACET_STUFE:
        facets["Bildungsstufe"] = [FACET_STUFE[group.stufe]]
    grades = grades_in(group.lead.klassenstufe.value)
    if grades:
        facets["Klassenstufe"] = [str(grade) for grade in sorted(set(grades))]
    if lehrplan.schularten:
        facets["Schulart"] = [lehrplan.schularten[0]]
    facets["Lehrplan"] = [lehrplan.iri]
    facets["Lehrplantitel"] = [lehrplan.label]
    return f"<!-- f: {format_marker(facets)} -->"


def _lehrplan_line(group: _Group, options: RenderOptions) -> list[str]:
    """Where the block's snippets come from, whole on one line (Jan, 2026-09-26): curriculum, state, school level,
    school type and grade, so a snippet read on its own still says so; a level or grade the data do not assert says
    what it was derived from."""
    lehrplan = group.lead.hit.lehrplan
    land = bundesland_by_code(group.land_code)
    parts = [f"[*{land.terminology}: {lehrplan.label}*]({lehrplan.iri})", land.name]
    stufe = group.lead.schulstufe
    if stufe.value != OHNE_STUFE:
        parts.append(stufe.value + ("" if stufe.from_data else f" *({stufe.source})*"))
    if lehrplan.schularten:
        parts.append(", ".join(lehrplan.schularten))
    klasse = group.lead.klassenstufe
    if klasse.value != OHNE_KLASSE:
        parts.append(klasse.value + ("" if klasse.from_data else f" *({klasse.source})*"))
    lines = [" · ".join(parts)]
    if options.facets_visible:
        visible: dict[str, list[str]] = {"Geltungsebene": ["Land"]}
        if group.stufe in FACET_STUFE:
            visible = {"Bildungsstufe": [FACET_STUFE[group.stufe]], **visible}
        lines.append(format_visible(visible))
    lines.append(_marker(group))
    return lines


def _item_line(match: CurriculumMatch) -> str:
    roles = ", ".join(ROLE_NAMES[role] for role in match.hit.rollen if role in ROLE_NAMES) or "Element"
    return f"- „{match.hit.label}“ ({roles}) · [Lehrplanelement]({match.hit.iri})"


def _bundled(match: CurriculumMatch) -> bool:
    """Found only through its heading and not confirmed by the LLM check: counted with its area, not listed (B, M22).

    In M22 such elements fitted less often (46 % against 55 %) and made most of the misses of a request with a
    subject. A heading-only element the LLM check rated 2 has been read for itself and stands on its own (D58).
    """
    return match.hit.matched_in == "parent" and match.note != 2


def _bundle_line(bundled: list[CurriculumMatch], *, after_others: bool) -> str:
    count = len(bundled)
    if after_others:
        noun = "weiteres Element" if count == 1 else "weitere Elemente"
    else:
        noun = "Element" if count == 1 else "Elemente"
    line = f"- *{count} {noun} dieses Bereichs; das Thema steht nur in der Überschrift*"
    area = next((match.hit.parent_iri for match in bundled if match.hit.parent_iri), None)
    return f"{line} · [Bereich im Lehrplan]({area})" if area else line


def _render_group(group: _Group, options: RenderOptions) -> list[str]:
    """One block from the opening marker to ``<!-- /f -->``, so a parser can lift it out with its facets."""
    lines = [*_lehrplan_line(group, options), "", f"**{group.bereich}**", ""]
    items = sorted(group.items, key=lambda match: (-match.score, match.hit.label))
    listed = [match for match in items if not _bundled(match)]
    bundled = [match for match in items if _bundled(match)]
    cap = options.max_items_per_group
    shown = listed if cap is None else listed[:cap]
    lines.extend(_item_line(match) for match in shown)
    if len(listed) > len(shown):
        lines.append(f"- *weitere {len(listed) - len(shown)} Elemente in diesem Bereich*")
    if bundled:
        lines.append(_bundle_line(bundled, after_others=bool(shown)))
    if not items:
        lines.append(f"- *{ROLE_NAMES[ROLE_THEMENBEREICH]}* · [Lehrplanelement]({group.lead.hit.iri})")
    lines.extend([END_MARKER, ""])
    return lines


def _table(by_land: Mapping[str, Counter[str]]) -> list[str]:
    columns = [PRIMAR, SEK_I, SEK_II]
    if any(counts.get(OHNE_STUFE) for counts in by_land.values()):
        columns.append(OHNE_STUFE)
    lines = ["| Bundesland | " + " | ".join(columns) + " |", "|---|" + "---:|" * len(columns)]
    for land in sorted(by_land):
        lines.append(f"| {land} | " + " | ".join(str(by_land[land].get(column, 0)) for column in columns) + " |")
    return lines


def render_curricula(
    result: MatchResult, *, meta: Mapping[str, str], options: RenderOptions
) -> tuple[str, dict[str, Any]]:
    """Markdown for part 2 plus a summary for the JSON answer and the audit."""
    info = coverage(meta)
    groups = _groups(result)
    by_land: dict[str, Counter[str]] = defaultdict(Counter)
    for match in result.matches:
        by_land[match.hit.lehrplan.bundesland][match.schulstufe.value] += 1
    summary: dict[str, Any] = {
        "coverage": info,
        "matches": len(result.matches),
        "bundled": sum(1 for group in groups for match in group.items if _bundled(match)),
        "total_hits": result.total_hits,
        "excluded_noise": result.excluded_noise,
        "lehrplaene": len({match.hit.lehrplan.iri for match in result.matches}),
        "laender": len(by_land),
        "by_land": {land: dict(counts) for land, counts in sorted(by_land.items())},
        "datenlage": {
            "stufe": dict(Counter(match.schulstufe.source for match in result.matches)),
            "klasse": dict(Counter(match.klassenstufe.source for match in result.matches)),
        },
        "keywords": list(result.keywords),
        "subject_terms": list(result.subject_terms),
    }

    lines = [PART_HEADING, "", _coverage_sentence(info), ""]
    if not result.matches:
        keywords = ", ".join(result.keywords) or "keine"
        lines.append(
            f"*Zu diesem Thema wurden in den vorliegenden Lehrplänen keine Lehrplanbezüge gefunden "
            f"(Stichwörter: {keywords}).*"
        )
        return "\n".join(lines) + "\n", summary

    subject = f"; Fach: {', '.join(result.subject_terms)}" if result.subject_terms else ""
    lines.append(
        f"{summary['matches']} Lehrplanelemente in {summary['lehrplaene']} Lehrplänen aus "
        f"{summary['laender']} Ländern; Stichwörter: {', '.join(result.keywords)}{subject}."
    )
    lines.append("")
    lines.extend(_table(by_land))
    lines.append("")

    for stufe in STUFEN_ORDER:
        stufe_groups = [group for group in groups if group.stufe == stufe]
        if not stufe_groups:
            continue
        lines.extend([f"### {stufe}", ""])
        lands = sorted({group.land_code for group in stufe_groups}, key=lambda code: bundesland_by_code(code).name)
        for code in lands:
            land_groups = [group for group in stufe_groups if group.land_code == code]
            land_groups.sort(
                key=lambda group: (
                    -max(match.score for match in (group.lead, *group.items)),
                    -len(group.items),
                    group.lead.hit.lehrplan.label,
                    group.bereich,
                )
            )
            lines.extend([f"#### {bundesland_by_code(code).name}", ""])
            cap = options.max_groups_per_land
            shown_groups = land_groups if cap is None else land_groups[:cap]
            for group in shown_groups:
                lines.extend(_render_group(group, options))
            remaining = len(land_groups) - len(shown_groups)
            if remaining > 0:
                noun = "weiterer 1 Eintrag" if remaining == 1 else f"weitere {remaining} Einträge"
                lines.extend([f"*{noun} in {bundesland_by_code(code).name} nicht aufgeführt (Längenbudget).*", ""])
    return "\n".join(lines).rstrip() + "\n", summary
