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

from app.domain.caller_values import listed
from app.domain.models import Citation, SectionStatus
from app.synthesis.citations import marker_numbers
from app.synthesis.facets import parse_marker
from app.synthesis.safe_markdown import unescape

if TYPE_CHECKING:
    from app.templates.schema import Template

# A heading starts a line and a marker or a row stays on its own: unanchored, "### " over and over, or a row without
# its closing bracket, made every try read to the end of an earlier compendium sent along (review of D60). A block
# runs to the heading of the next block - a "### " line with a marker under it - or to the next part: it ended at any
# "### ", and the text after an editor's own subheading was lost while the block counted as kept. The facets are read
# up to the hash, so a marker written before quotes were encoded still reads (audit 2026-09-29, A01).
SECTION_RE = re.compile(
    r"^### (?P<title>[^\n]+)\n(?P<marker><!-- kompendium:section id=(?P<slot>\S+) status=(?P<status>[^ \n]+)"
    r"(?: facets=\"(?P<facets>[^\n]*?)\")? hash=(?P<hash>[0-9a-f]+) -->)\n\n?(?P<text>.*?)"
    r"(?=\n### [^\n]*\n<!-- kompendium:section |\n## |\Z)",
    re.DOTALL | re.MULTILINE,
)
# Every marker line, read or not: one the pattern above does not take would keep nothing of its block
MARKER_LINE_RE = re.compile(r"^<!-- kompendium:section\b[^\n]*", re.MULTILINE)
# A row of the citation table as the sources block writes it: the title escaped, as a link where the source had a web
# address, else alone (audit 2026-09-28, SE-16). A link in angle brackets holds spaces or parentheses; a link without
# them runs to the last closing parenthesis before its cell ends, as earlier documents wrote "Merkur (Planet)" (audit
# 2026-09-27, KO-02). Every part stays on its line, so the scan stays linear. Four digits are more than a compendium
# numbers; int() refuses over 4,300 (KO-08).
ROW_RE = re.compile(
    r"^\| \[(?P<number>\d{1,4})\] \| "
    r"(?:\[(?P<title>(?:\\.|[^\\\]\n])*)\]\((?:<(?P<pointed>[^>\n]*)>|(?P<url>\S*))\)|(?P<plain>[^|\n]*?)) "
    r"\| (?P<heading>[^|\n]*) \| (?P<snippet>[^|\n]*) \|$",
    re.MULTILINE,
)


class UnknownSectionsError(ValueError):
    """Names in ``regenerate_sections`` that are no block of the template; the API answers 422 with the known ones."""

    def __init__(self, unknown: Sequence[str], known: Sequence[str]) -> None:
        self.unknown, self.known = list(unknown), list(known)
        super().__init__(
            f"Unbekannte Bausteine in regenerate_sections: {listed(self.unknown)}. Das Template kennt "
            f"{', '.join(self.known)}"
        )


class UnplacedSectionsError(ValueError):
    """Blocks of an earlier compendium that should stay but have no place in the template of the request; the API
    answers 422. Another template, or another TEMPLATE_DEFAULT, dropped every reviewed block without a word (audit
    2026-09-29, T5)."""

    def __init__(self, unplaced: Sequence[str], template_id: str, known: Sequence[str]) -> None:
        self.unplaced, self.template_id, self.known = list(unplaced), template_id, list(known)
        super().__init__(
            f"Bausteine aus existing_markdown, die erhalten bleiben sollen, hat das Template {template_id} nicht: "
            f"{listed(self.unplaced)}. Es kennt {listed(self.known)}; template_id des früheren Kompendiums angeben"
        )


class UnreadableDocumentError(ValueError):
    """An earlier compendium whose blocks cannot all be read safely; the API answers 422 and names what it met.

    A marker the parser could not read kept nothing of its block, and the block was made anew without a word - a
    reviewed one as well (audit 2026-09-29, A01). Which of two blocks with one id should stay cannot be decided. A
    status the service does not know was read as reviewed, so a block "in-pruefung" passed the default filter of
    the topic page as reviewed; the service has only ever written its own statuses (T5).
    """

    def __init__(
        self, unreadable: Sequence[str] = (), doubled: Sequence[str] = (), unknown: Sequence[str] = ()
    ) -> None:
        self.unreadable, self.doubled, self.unknown = list(unreadable), list(doubled), list(unknown)
        problems = []
        if self.unreadable:
            problems.append(f"nicht lesbare Markierungen: {listed(self.unreadable)}")
        if self.doubled:
            problems.append(f"mehrfach vorhandene Bausteine: {listed(self.doubled)}")
        if self.unknown:
            known = ", ".join(status.value for status in SectionStatus)
            problems.append(
                f"Bausteine mit einem Status, den der Dienst nicht kennt: {listed(self.unknown)} (er kennt {known})"
            )
        super().__init__(
            "existing_markdown lässt sich nicht sicher lesen: "
            + "; ".join(problems)
            + ". Ein Baustein, dessen Markierung der Dienst nicht liest, würde sonst still neu erzeugt. Die "
            "Markierung steht auf der Zeile unter der Überschrift ihres Bausteins: "
            "<!-- kompendium:section id=… status=… hash=… -->"
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
    """Every block of an earlier compendium by slot id, with its status, facets and citations.

    A text area sends CRLF, and CommonMark ends a line at a lone CR: every line end is read as LF. A marker the
    pattern cannot read, or a block id that stands twice, is an ``UnreadableDocumentError``.
    """
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    rows = _citation_rows(markdown)
    sections: dict[str, PreservedSection] = {}
    read: set[int] = set()
    doubled: list[str] = []
    unknown: list[str] = []
    for match in SECTION_RE.finditer(markdown):
        slot_id = match.group("slot")
        if slot_id in sections:
            doubled.append(slot_id)
        read.add(match.start("marker"))
        status = _status(match.group("status"))
        if status is None:
            unknown.append(f"{slot_id} ({match.group('status')})")
            continue
        text = match.group("text").rstrip()
        sections[slot_id] = PreservedSection(
            slot_id=slot_id,
            status=status,
            text=text,
            facets=parse_marker(match.group("facets") or ""),
            citations=[rows[number] for number in marker_numbers(text) if number in rows],
        )
    unreadable = [line.group(0) for line in MARKER_LINE_RE.finditer(markdown) if line.start() not in read]
    if unreadable or doubled or unknown:
        raise UnreadableDocumentError(unreadable, doubled, unknown)
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
        title = match.group("title") if match.group("title") is not None else match.group("plain")
        # read back as typed: the sources block escapes them again, and an escape read as text would double
        rows[number] = Citation(
            number=number,
            source_id="",
            chunk_id="",
            source_title=unescape(title.strip()),
            source_url=(match.group("pointed") or match.group("url") or "").strip(),
            section_heading=unescape(match.group("heading").strip()),
            snippet=unescape(match.group("snippet").strip()),
        )
    return rows


def _status(value: str) -> SectionStatus | None:
    try:
        return SectionStatus(value)
    except ValueError:
        return None
