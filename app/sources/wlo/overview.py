"""Part 3 rendering (PLAN.md 6.2): purpose, key figures, material blocks, sub-collections one level down.

No judgement and no invention: a missing description stays visibly missing. Every block sits between a
facet marker (collection id, subject, level) and ``<!-- /f -->`` so it can be parsed out later, like
the curriculum blocks of part 2. Nothing is cut unless a cap is configured (decision D23).

Each material is a fenced ``::: wlo-material`` block carrying its node id in the preview URL, so another
system can lift the materials out of the markdown and look them up in the repository; the README section
"Materialblöcke in Teil 3" is the contract.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.sources.wlo.models import CollectionInfo, MaterialRef, SubCollection, license_url
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
MATERIAL_FENCE = "wlo-material"  # the block a downstream parser looks for; the README documents its shape
_LINK_TEXT_ESCAPE = str.maketrans({"[": r"\[", "]": r"\]"})


class RepositoryUrls(Protocol):
    """The public URLs of a node in the repository the collection came from (``EduSharingClient``)."""

    def render_url(self, node_id: str) -> str: ...

    def preview_url(self, node_id: str) -> str: ...


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


def _link(text: str, url: str) -> str:
    """A markdown link whose text and target cannot break out of it.

    Titles and URLs come from the repository, so they are untrusted input for a format that is meant to be
    parsed: brackets in the text are escaped, and a target with spaces or parentheses goes in angle brackets,
    which in turn needs the angle brackets of the URL itself percent-encoded.
    """
    if any(char in url for char in " ()<>"):
        url = f"<{url.replace('<', '%3C').replace('>', '%3E')}>"
    return f"[{text.translate(_LINK_TEXT_ESCAPE)}]({url})"


def _metadata_line(ref: MaterialRef) -> str:
    """Description, keywords, type and level on one line.

    The line is collapsed to single spaces at the end: a keyword the repository stores with a line break
    would otherwise put its own lines into the block, and one reading ``:::`` would close it early.
    """
    parts = []
    sentence = first_sentence(ref.description)
    if sentence:
        parts.append(sentence)
    if ref.keywords:
        parts.append("Schlagwörter: " + ", ".join(ref.keywords[:MAX_KEYWORDS]))
    parts.extend(label for label in (*ref.resource_types[:2], *ref.educational_contexts[:2]) if label)
    return " ".join(" · ".join(parts).split())


def _material_block(ref: MaterialRef, urls: RepositoryUrls) -> list[str]:
    """One material as a fenced block: preview, titled link, licence, metadata.

    The preview URL carries the material's node id, which is what another system needs to look it up; the
    title links to the material itself, or to its page in the repository when it has no own URL, so a parser
    always finds exactly one target. The licence links its deed where there is one.
    """
    title = ref.title or "ohne Titel"
    deed = license_url(ref.license_key, ref.license_version)
    licence = _link(ref.license, deed) if deed else ref.license
    lines = [
        f"::: {MATERIAL_FENCE}",
        f"!{_link(title, urls.preview_url(ref.node_id))}",
        "",
        f"{_link(f'**{title}**', ref.url or urls.render_url(ref.node_id))} — Lizenz: {licence}",
    ]
    metadata = _metadata_line(ref)
    if metadata:
        lines.extend(["", metadata])
    lines.append(":::")
    return lines


def _item_lines(refs: Sequence[MaterialRef], options: OverviewOptions, urls: RepositoryUrls) -> list[str]:
    """The material blocks of one list, each separated by a blank line so every fence stands on its own block."""
    if not refs:
        return ["", NO_ITEMS, ""]
    shown = refs if options.max_items is None else refs[: options.max_items]
    lines = [line for ref in shown for line in ("", *_material_block(ref, urls))]
    if len(refs) > len(shown):
        lines.extend(["", f"*weitere {len(refs) - len(shown)} Inhalte*"])
    return [*lines, ""]


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
    urls: RepositoryUrls,
    options: OverviewOptions,
    incomplete: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Markdown for part 3 plus a summary for the JSON answer and the audit; ``incomplete`` adds a visible hint."""
    facets = _collection_facets(info)
    head = [f"**{info.title}** · {_link('Sammlung öffnen', urls.render_url(info.id))}"]
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
    lines.extend(["### Inhalte der Sammlung", "", _marker(facets), *_item_lines(refs, options, urls), END_MARKER, ""])
    if subs:
        lines.extend(["### Untersammlungen", ""])
        for sub in subs:
            lines.extend(
                [
                    f"#### {sub.info.title}",
                    "",
                    _marker({"Sammlung": [sub.info.id], "Übergeordnet": [info.id]}),
                    sub.info.description or NO_DESCRIPTION,
                    *_item_lines(sub.refs, options, urls),
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
