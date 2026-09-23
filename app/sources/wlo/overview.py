"""Part 3 rendering (PLAN.md 6.2): purpose, key figures, one line per node, sub-collections one level down.

No judgement and no invention: a missing description stays visibly missing. Every block sits between a
facet marker (collection id, subject, level) and ``<!-- /f -->`` so it can be parsed out later, like
the curriculum blocks of part 2. Nothing is cut unless a cap is configured (decision D23).

Every node - the collection, each sub-collection, each content - is one list line ``- <kind>: … · nodeId: <id>``,
so another system can read the tree back from the markdown and look every node up in the repository; the README
section "Knotenzeilen in Teil 3" is the contract.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.sources.wlo.models import CollectionInfo, MaterialRef, SubCollection, one_line
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
MAX_KEYWORDS = 5
MAX_SENTENCE_CHARS = 240
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LINK_TEXT_ESCAPE = str.maketrans({"[": r"\[", "]": r"\]"})
_LEADING_DASH = re.compile(r"^(\s*)-")


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


def _description(text: str) -> str:
    """The collection's description as its editors wrote it, with their lines and paragraphs, but without a line that
    reads as a node: every line break becomes a plain one - CommonMark also breaks at CR, ``str.splitlines`` at
    U+2028 and more - and a dash that starts a line is escaped, which CommonMark shows as the dash it is. A list the
    editors typed therefore reads as running text."""
    return "\n".join(_LEADING_DASH.sub(lambda match: match[1] + r"\-", line) for line in text.splitlines())


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


def _link_target(url: str) -> str:
    """``url`` as a markdown link target that cannot end early: with spaces or parentheses it goes in angle
    brackets - ``…/wiki/Linse_(Optik)`` is a real material URL, which a parser reading up to the first ``)``
    would cut - and angle brackets inside it are percent-encoded."""
    if any(char in url for char in " ()<>"):
        return f"<{url.replace('<', '%3C').replace('>', '%3E')}>"
    return url


def _node_line(kind: str, title: str, url: str, fields: Sequence[str], node_id: str) -> str:
    """One node of the collection tree on one line: ``- <kind>: <title> · <fields> · nodeId: <id>``.

    The title is the link where the node has a URL, its brackets escaped so it stays one link. Every value comes
    from the repository, where an editor can type anything, so the whole line is collapsed: a line break would
    otherwise split the node or start a line that reads as another one. The URL is collapsed first, so that a
    line break in it turns into a space before its target is chosen.
    """
    heading = f"**{title or 'ohne Titel'}**"
    target = one_line(url)
    if target:
        heading = f"[{heading.translate(_LINK_TEXT_ESCAPE)}]({_link_target(target)})"
    return "- " + one_line(
        " · ".join([f"{kind}: {heading}", *(field for field in fields if field), f"nodeId: {node_id}"])
    )


def _item_line(ref: MaterialRef) -> str:
    fields = [first_sentence(ref.description)]
    if ref.keywords:
        fields.append("Schlagwörter: " + ", ".join(ref.keywords[:MAX_KEYWORDS]))
    fields.extend((*ref.resource_types[:2], *ref.educational_contexts[:2], ref.license))
    return _node_line("Inhalt", ref.title, ref.url, fields, ref.node_id)


def _item_lines(refs: Sequence[MaterialRef], options: OverviewOptions, indent: str = "") -> list[str]:
    """The content lines of one list; ``indent`` nests them under the sub-collection line above them."""
    if not refs:
        return [f"{indent}- {NO_ITEMS}" if indent else NO_ITEMS]
    shown = refs if options.max_items is None else refs[: options.max_items]
    lines = [indent + _item_line(ref) for ref in shown]
    if len(refs) > len(shown):
        lines.append(f"{indent}- *weitere {len(refs) - len(shown)} Inhalte*")
    return lines


def _counts(label: str, counter: Counter[str]) -> str:
    if not counter:
        return ""
    return f"{label}: " + ", ".join(f"{name} ({count})" for name, count in counter.most_common())


def _key_figures(refs: Sequence[MaterialRef], subs: Sequence[SubCollectionContents]) -> tuple[str, dict[str, Any]]:
    """The key figures line and its summary. The line names labels straight from the repository, so it is collapsed
    like a material line; the summary keeps them as the repository gave them."""
    types = Counter(label for ref in refs for label in ref.resource_types)
    contexts = Counter(label for ref in refs for label in ref.educational_contexts)
    subjects = Counter(label for ref in refs for label in ref.subjects)
    licenses = Counter(ref.license for ref in refs)
    parts = [
        f"Kennzahlen: {len(refs)} Inhalte, {len(subs)} Untersammlungen",
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
    return one_line("; ".join(part for part in parts if part)), summary


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
    head = []
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
        _node_line("Sammlung", info.title, render_url(info.id), head, info.id),
        "",
        _description(info.description) or NO_DESCRIPTION,
        "",
        figures,
        END_MARKER,
        "",
    ]
    lines.extend(["### Inhalte der Sammlung", "", _marker(facets), *_item_lines(refs, options), END_MARKER, ""])
    if subs:
        lines.extend(["### Untersammlungen", ""])
        for sub in subs:
            # no link for a sub-collection: that would ask render_url for every one of them, and a broken id
            # there would take the whole part down; its node id names it
            first = first_sentence(sub.info.description)
            lines.extend(
                [
                    _marker({"Sammlung": [sub.info.id], "Übergeordnet": [info.id]}),
                    _node_line("Untersammlung", sub.info.title, "", [first], sub.info.id),
                    *_item_lines(sub.refs, options, indent="  "),
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
