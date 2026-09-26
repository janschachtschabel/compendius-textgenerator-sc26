"""Partial regeneration (PLAN.md 4.6): keep blocks of an earlier compendium, make the rest anew.

The markers of a compendium say which block is which, what its status is and which facets it carries, and the
citation table says what a number points to. A block marked ``redaktionell-geprüft`` is kept as it stands; with
``regenerate_sections`` only the named blocks are made anew and everything else is kept. A kept block keeps its
citation numbers, so its text is not touched at all; the new blocks are numbered after the highest kept number,
and the sources block lists both. Sources that only the kept blocks cite appear in the citation table with what
the old document said about them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.models import Citation, SectionStatus
from app.synthesis.citations import marker_numbers

if TYPE_CHECKING:
    from app.templates.schema import Template

# A heading starts a line and a marker or a row stays on its own: unanchored, "### " over and over, or a row without
# its closing bracket, made every try read to the end of an earlier compendium sent along (review of D60)
SECTION_RE = re.compile(
    r"^### (?P<title>[^\n]+)\n<!-- kompendium:section id=(?P<slot>\S+) status=(?P<status>[^ \n]+)"
    r"(?: facets=\"(?P<facets>[^\"\n]*)\")? hash=(?P<hash>[0-9a-f]+) -->\n\n(?P<text>.*?)(?=\n### |\n## |\Z)",
    re.DOTALL | re.MULTILINE,
)
ROW_RE = re.compile(
    r"^\| \[(?P<number>\d+)\] \| \[(?P<title>[^\]\n]*)\]\((?P<url>[^)\n]*)\) \| (?P<heading>[^|\n]*) "
    r"\| (?P<snippet>[^|\n]*) \|$",
    re.MULTILINE,
)


class UnknownSectionsError(ValueError):
    """Names in ``regenerate_sections`` that are no block of the template; the API answers 422 with the known ones."""

    def __init__(self, unknown: Sequence[str], known: Sequence[str]) -> None:
        self.unknown, self.known = list(unknown), list(known)
        super().__init__(
            f"Unbekannte Bausteine in regenerate_sections: {', '.join(self.unknown)}. Das Template kennt "
            f"{', '.join(self.known)}"
        )


def check_names(regenerate_sections: Sequence[str] | None, template: Template) -> None:
    """Refuse a name that is no block id of the template: it used to change nothing without a word."""
    ids = {slot.id for slot in template.slots}
    unknown = [name for name in regenerate_sections or () if name not in ids]
    if unknown:
        raise UnknownSectionsError(unknown, [f"{slot.id} ({slot.slot})" for slot in template.slots])


@dataclass(frozen=True)
class PreservedSection:
    """A block of the earlier document, kept word for word together with the citations it names."""

    slot_id: str
    status: SectionStatus
    text: str
    facets: dict[str, list[str]] = field(default_factory=dict)
    citations: list[Citation] = field(default_factory=list)


def parse_document(markdown: str) -> dict[str, PreservedSection]:
    """Every block of an earlier compendium by slot id, with its status, facets and citations."""
    rows = _citation_rows(markdown)
    sections: dict[str, PreservedSection] = {}
    for match in SECTION_RE.finditer(markdown):
        text = match.group("text").rstrip()
        status = _status(match.group("status"))
        sections[match.group("slot")] = PreservedSection(
            slot_id=match.group("slot"),
            status=status,
            text=text,
            facets=_facets(match.group("facets") or ""),
            citations=[rows[number] for number in marker_numbers(text) if number in rows],
        )
    return sections


def to_keep(
    existing: Mapping[str, PreservedSection], regenerate_sections: Sequence[str] | None
) -> dict[str, PreservedSection]:
    """Which blocks stay: the reviewed ones always, and with ``regenerate_sections`` everything not named."""
    named = set(regenerate_sections or ())
    keep: dict[str, PreservedSection] = {}
    for slot_id, section in existing.items():
        if slot_id in named:
            continue
        if regenerate_sections is not None or section.status is SectionStatus.REVIEWED:
            keep[slot_id] = section
    return keep


def _citation_rows(markdown: str) -> dict[int, Citation]:
    """The citation table of the earlier document; source and chunk ids are gone, title and link are enough."""
    rows: dict[int, Citation] = {}
    for match in ROW_RE.finditer(markdown):
        number = int(match.group("number"))
        rows[number] = Citation(
            number=number,
            source_id="",
            chunk_id="",
            source_title=match.group("title").strip(),
            source_url=match.group("url").strip(),
            section_heading=match.group("heading").strip(),
            snippet=match.group("snippet").strip(),
        )
    return rows


def _status(value: str) -> SectionStatus:
    try:
        return SectionStatus(value)
    except ValueError:  # a status this version does not know: the block is kept, the status is what it was
        return SectionStatus.REVIEWED


def _facets(marker: str) -> dict[str, list[str]]:
    """The facets of a marker (``Name=Wert|Wert; Name=Wert``) as the writer holds them."""
    facets: dict[str, list[str]] = {}
    for part in marker.split("; "):
        name, _, values = part.partition("=")
        if name.strip() and values:
            facets[name.strip()] = [value for value in values.split("|") if value]
    return facets
