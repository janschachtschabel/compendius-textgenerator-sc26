"""Part 3 rendering (PLAN.md 6.2): purpose, key figures, compact material lists, sub-collections one level down.

No judgement and no invention: a missing description stays visibly missing. Every block sits between a
facet marker (collection id, subject, level) and ``<!-- /f -->`` so it can be parsed out later, like
the curriculum blocks of part 2. Nothing is cut unless a cap is configured (decision D23).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.sources.wlo.models import CollectionInfo, MaterialRef, SubCollection
from app.synthesis.facets import END_MARKER, bildungsstufe_facet, format_marker

PART_HEADING = "## Teil 3 · Die Sammlung im Überblick"
NO_DESCRIPTION = "*Für diese Sammlung ist keine Beschreibung hinterlegt.*"
NO_ITEMS = "*Keine Inhalte gelistet.*"
INCOMPLETE_TEXT = (
    "*Das Zeitbudget der Anfrage war erschöpft; die Listen dieses Überblicks sind möglicherweise unvollständig.*"
)
COLLECTION_TYPES = {
    "EDITORIAL": "redaktionelle Sammlung",
    "EDITORIAL_GROUP": "redaktionelle Gruppensammlung",
    "PRIVATE": "private Sammlung",
}
MAX_KEYWORDS = 8
MAX_SENTENCE_CHARS = 240
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class OverviewOptions:
    max_items: int | None = None  # per list; None renders every material


@dataclass(frozen=True)
class SubCollectionContents:
    info: SubCollection
    refs: tuple[MaterialRef, ...] = ()


def first_sentence(text: str) -> str:
    """The one-sentence description of a material: its first sentence, capped for the list line."""
    text = " ".join(text.split())
    if not text:
        return ""
    sentence = _SENTENCE_END.split(text, maxsplit=1)[0]
    if len(sentence) > MAX_SENTENCE_CHARS:
        sentence = sentence[: MAX_SENTENCE_CHARS - 1].rstrip() + "…"
    return sentence


def _marker(facets: dict[str, list[str]]) -> str:
    return f"<!-- f: {format_marker(facets)} -->"


def _collection_facets(info: CollectionInfo) -> dict[str, list[str]]:
    facets: dict[str, list[str]] = {"Sammlung": [info.id]}
    if info.subject_labels:
        facets["Fach"] = list(info.subject_labels)
    levels = [level for level in (bildungsstufe_facet(label) for label in info.educational_contexts) if level]
    if levels:
        facets["Bildungsstufe"] = list(dict.fromkeys(levels))
    return facets


def _item_line(ref: MaterialRef) -> str:
    parts = [f"**{ref.title or 'ohne Titel'}**"]
    sentence = first_sentence(ref.description)
    if sentence:
        parts.append(sentence)
    if ref.keywords:
        parts.append("Schlagwörter: " + ", ".join(ref.keywords[:MAX_KEYWORDS]))
    parts.extend(label for label in (*ref.resource_types[:2], *ref.educational_contexts[:2]) if label)
    parts.append(ref.license)
    if ref.url:
        parts.append(f"[Material]({ref.url})")
    return "- " + " · ".join(parts)


def _item_lines(refs: Sequence[MaterialRef], options: OverviewOptions) -> list[str]:
    if not refs:
        return [NO_ITEMS]
    shown = refs if options.max_items is None else refs[: options.max_items]
    lines = [_item_line(ref) for ref in shown]
    if len(refs) > len(shown):
        lines.append(f"- *weitere {len(refs) - len(shown)} Inhalte*")
    return lines


def _counts(label: str, counter: Counter[str]) -> str:
    if not counter:
        return ""
    return f"{label}: " + ", ".join(f"{name} ({count})" for name, count in counter.most_common())


def _key_figures(refs: Sequence[MaterialRef], subs: Sequence[SubCollectionContents]) -> tuple[str, dict[str, Any]]:
    types = Counter(label for ref in refs for label in ref.resource_types)
    contexts = Counter(label for ref in refs for label in ref.educational_contexts)
    subjects = Counter(label for ref in refs for label in ref.subjects)
    licenses = Counter(ref.license for ref in refs)
    parts = [
        f"Kennzahlen: {len(refs)} Inhalte, {len(subs)} Untersammlungen.",
        _counts("Materialtypen", types),
        _counts("Bildungsstufen", contexts),
        _counts("Fächer", subjects),
        _counts("Lizenzen", licenses),
    ]
    summary = {
        "resource_types": dict(types),
        "educational_contexts": dict(contexts),
        "subjects": dict(subjects),
        "licenses": dict(licenses),
    }
    return "; ".join(part for part in parts if part), summary


def render_collection_overview(
    info: CollectionInfo,
    refs: Sequence[MaterialRef],
    subs: Sequence[SubCollectionContents],
    *,
    render_url: Callable[[str], str],
    options: OverviewOptions,
    incomplete: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Markdown for part 3 plus a summary for the JSON answer and the audit; ``incomplete`` adds a visible hint."""
    facets = _collection_facets(info)
    head = [f"**{info.title}** · [Sammlung öffnen]({render_url(info.id)})"]
    if info.subject_labels:
        head.append("Fach: " + ", ".join(info.subject_labels))
    if info.educational_contexts:
        head.append("Bildungsstufe: " + ", ".join(info.educational_contexts))
    if info.collection_type:
        head.append(COLLECTION_TYPES.get(info.collection_type, info.collection_type))
    if info.modified_at:
        head.append(f"Stand {info.modified_at[:10]}")
    figures, summary = _key_figures(refs, subs)

    lines = [
        PART_HEADING,
        "",
        _marker(facets),
        " · ".join(head),
        "",
        info.description or NO_DESCRIPTION,
        "",
        figures,
        END_MARKER,
        "",
    ]
    lines.extend(["### Inhalte der Sammlung", "", _marker(facets), *_item_lines(refs, options), END_MARKER, ""])
    if subs:
        lines.extend(["### Untersammlungen", ""])
        for sub in subs:
            lines.extend(
                [
                    f"#### {sub.info.title}",
                    "",
                    _marker({"Sammlung": [sub.info.id], "Übergeordnet": [info.id]}),
                    sub.info.description or NO_DESCRIPTION,
                    "",
                    *_item_lines(sub.refs, options),
                    END_MARKER,
                    "",
                ]
            )
    if incomplete:
        lines.extend([INCOMPLETE_TEXT, ""])
    summary.update(
        {
            "incomplete": incomplete,
            "collection_id": info.id,
            "title": info.title,
            "materials": len(refs),
            "subcollections": len(subs),
            "missing_descriptions": sum(1 for ref in refs if not ref.description),
            "subcollection_materials": {sub.info.title: len(sub.refs) for sub in subs},
        }
    )
    return "\n".join(lines).rstrip() + "\n", summary
