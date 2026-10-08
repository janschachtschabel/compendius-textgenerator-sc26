"""The sources of an earlier compendium that only its kept blocks cite (PLAN.md 4.6).

A regeneration builds a new corpus, and a source a kept block cites may not be in it: another ``max_articles``, no
knowledge collection this time, a newer archive. Its row in the citation table stayed, its entry in the sources list
did not - the authors and the licence a CC BY(-SA) text has to name - and its citations lost their source id (audit
2026-09-29, A04). ``read_sources`` reads the entries back as ``build_sources_section`` wrote them, ``attribute`` gives
every citation of a kept block its source and names those it cannot.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.compose.regeneration import PreservedSection
from app.domain.licences import PROJECT_LABELS
from app.domain.models import Citation, Source
from app.markup.citations import marker_numbers
from app.markup.safe_markdown import unescape

ENTRY = "- **"
TULLU = "  - TULLU: "
ARCHIVE = "  - Archiv: "
STAND = ", Stand des Archivs "
ENTRY_PATH = " · Eintrag "
# The fields of a TULLU line after the title, read from the right: a title may hold " · " itself
FIELDS = (" · Ursprungsort ", " · Link ", " · Lizenz ", " · Urheber ")
TITLE_OPEN, TITLE_CLOSE = "Titel „", "“"
UNKNOWN_AUTHORS = "unbekannt"  # what build_sources_section names for a project it has no label for


@dataclass(frozen=True)
class Attribution:
    """The kept blocks with the source id of every citation, the entries they carry into the new sources list, and
    the numbers of their citations whose source neither the new corpus nor the earlier list names."""

    kept: dict[str, PreservedSection]
    carried: list[Source]
    unattributed: list[int]


def read_sources(markdown: str) -> list[Source]:
    """The entries of the sources list of an earlier compendium, as sources. Every step splits on known text, so a
    hostile document costs linear time."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found: list[Source] = []
    for index, line in enumerate(lines):
        if not line.startswith(TULLU) or index == 0 or not lines[index - 1].startswith(ENTRY):
            continue
        fields = _tullu(line[len(TULLU) :])
        if fields is None:
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        archive = following[len(ARCHIVE) :] if following.startswith(ARCHIVE) else ""
        found.append(_source(lines[index - 1], fields, archive))
    return found


def attribute(kept: Mapping[str, PreservedSection], markdown: str, sources: Sequence[Source]) -> Attribution:
    """Every citation of a kept block with the id of its source: one of the new corpus when it is there, else the
    entry the earlier document wrote, which then joins the new sources list. A citation neither names, and a marker
    without its row in the citation table, count as unattributed: the import is incomplete there."""
    if not kept:
        return Attribution({}, [], [])
    current, earlier = _index(sources), _index(read_sources(markdown))
    carried: dict[str, Source] = {}
    unattributed: set[int] = set()
    attributed: dict[str, PreservedSection] = {}
    for slot_id, block in kept.items():
        citations: list[Citation] = []
        for citation in block.citations:
            source = _find(current, citation)
            if source is None:
                source = _find(earlier, citation)
                if source is not None:
                    carried.setdefault(source.source_id, source)
            if source is None:
                unattributed.add(citation.number)
                citations.append(citation)
            else:
                citations.append(citation.model_copy(update={"source_id": source.source_id}))
        unattributed.update(set(marker_numbers(block.text)) - {citation.number for citation in block.citations})
        attributed[slot_id] = dataclasses.replace(block, citations=citations)
    return Attribution(attributed, list(carried.values()), sorted(unattributed))


def _index(sources: Sequence[Source]) -> tuple[dict[str, Source], dict[str, Source]]:
    return {source.url: source for source in sources if source.url}, {source.title: source for source in sources}


def _find(index: tuple[dict[str, Source], dict[str, Source]], citation: Citation) -> Source | None:
    """The source of ``citation``: by its address where the row has one - two materials may share a title - else by
    its title. The row writes the address as the entry's link does (``link_target`` changes neither)."""
    by_url, by_title = index
    if citation.source_url:
        return by_url.get(citation.source_url)
    return by_title.get(citation.source_title)


def _tullu(text: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    rest = text
    for name in FIELDS:
        rest, found, value = rest.rpartition(name)
        if not found:
            return None
        values[name.strip(" ·")] = unescape(value)
    if len(rest) < len(TITLE_OPEN) + len(TITLE_CLOSE) or not (
        rest.startswith(TITLE_OPEN) and rest.endswith(TITLE_CLOSE)
    ):
        return None
    values["Titel"] = unescape(rest[len(TITLE_OPEN) : -len(TITLE_CLOSE)])
    return values


def _source(head: str, fields: Mapping[str, str], archive: str) -> Source:
    origin, authors, url, title = fields["Ursprungsort"], fields["Urheber"], fields["Link"], fields["Titel"]
    project = next((key for key, labels in PROJECT_LABELS.items() if labels[0] == origin), origin)
    # wiki projects credit their community, a project without a label is "unbekannt": no author of the source itself
    credited = PROJECT_LABELS[project][2] if project in PROJECT_LABELS else UNKNOWN_AUTHORS
    zim_file, entry_path = _archive(archive)
    return Source(
        source_id="kept:" + hashlib.sha256((url or title).encode("utf-8")).hexdigest()[:12],
        project=project,
        title=title,
        url=url,
        zim_file=zim_file,
        zim_date=_stand(head),
        entry_path=entry_path,
        license=fields["Lizenz"],
        authors=[] if authors == credited else authors.split(", "),
    )


def _stand(head: str) -> str | None:
    """The date of the archive in the entry's line: ``…, Stand des Archivs 2026-01`` before any visible facets."""
    _, found, rest = head.rpartition(STAND)
    if not found:
        return None
    return unescape(rest.split(" [", 1)[0].strip()) or None


def _archive(text: str) -> tuple[str | None, str | None]:
    """File and entry of ``Archiv: `file` · Eintrag `path```, as ``code_span`` wrote them."""
    if not text:
        return None, None
    file_part, found, entry_part = text.partition(ENTRY_PATH)
    return _code(file_part), _code(entry_part) if found else None


def _code(text: str) -> str | None:
    """The inside of a code span of ``code_span``: its fence is longer than any run of backticks in it, and a space
    pads it where it starts or ends with a backtick."""
    text = text.strip()
    fence = len(text) - len(text.lstrip("`"))
    if not fence or len(text) <= 2 * fence or not text.endswith("`" * fence):
        return None
    inside = text[fence:-fence]
    if len(inside) >= 2 and inside[0] == inside[-1] == " " and "`" in (inside[1], inside[-2]):
        inside = inside[1:-1]
    return inside or None
