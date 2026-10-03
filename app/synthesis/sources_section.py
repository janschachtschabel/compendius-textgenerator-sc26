"""Generated block: sources with provenance, TULLU attribution and the citation table.

Titles, addresses, authors and licences of materials come from a repository anyone may type into, and the
snippets are the sources' words: each goes in through ``plain_label``, and only a web address becomes a link
(audit 2026-09-28, SE-16).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.models import Citation, Source
from app.synthesis.safe_markdown import cell_link, code_span, plain_label, table_cell, web_link

PROJECT_LABELS = {
    "wikipedia": ("Wikipedia", "Nachschlagewerk", "Wikipedia-Autorinnen und -Autoren", "hoch"),
    "klexikon": ("Klexikon", "Nachschlagewerk (einfache Sprache)", "Klexikon-Autorinnen und -Autoren", "hoch"),
    "wikibooks": ("Wikibooks", "Grundlagenwerk", "Wikibooks-Autorinnen und -Autoren", "mittel"),
    "wikiversity": ("Wikiversity", "Grundlagenwerk (Hochschule)", "Wikiversity-Autorinnen und -Autoren", "mittel"),
    "wlo_material": ("WirLernenOnline", "Sammlung & Archiv", "nicht angegeben", "mittel"),
}


# The licences of texts part 1 may pass on under CC BY-SA 4.0: the public domain, CC BY and CC BY-SA. A knowledge
# collection brings materials of any licence since D70; the block called them all free (audit 2026-10-02, A09)
MAX_NAMED_RESTRICTED = 5  # sources without a free licence the note names; the list above has them all
_FREE_LICENCE = re.compile(r"CC0 1\.0|Public Domain Mark|CC BY(-SA)?( \d(\.\d)?)?")


def is_free(licence: str) -> bool:
    """Whether a licence, as ``Source.license`` names it, lets part 1 pass the text on under CC BY-SA 4.0."""
    return _FREE_LICENCE.fullmatch(licence.strip()) is not None


# Access is not the licence: a CC licence with NC or ND publishes the text openly and restricts its use, and the
# repository says "frei zugänglich (keine OER-Lizenz)" outright (app/sources/wlo/models.py). In the Optik collection
# of the staging 12 of 13 materials without a free licence were one of them, the thirteenth names no licence
# (2026-10-03); only there access is unknown and the lint names the missing facet.
FREELY_ACCESSIBLE = ("CC", "Public Domain Mark", "frei zugänglich")


def freely_accessible(licence: str) -> bool:
    """Whether anyone may read a source with this licence, as ``Source.license`` names it."""
    return licence.strip().startswith(FREELY_ACCESSIBLE)


def _enumerate(items: Sequence[str]) -> str:
    """German enumeration: ``A``, ``A und B``, ``A, B und C``."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} und {items[-1]}"


def build_sources_section(sources: Sequence[Source], citations: Sequence[Citation], facets_visible: bool) -> str:
    restricted = [source for source in sources if not is_free(source.license)]
    stock = "folgenden Quellen" if restricted else "folgenden freien Wissensbeständen"
    lines: list[str] = [f"Die Inhalte von Teil 1 stammen aus {stock}:", ""]
    for source in sources:
        label, form, authors, trust = PROJECT_LABELS.get(
            source.project, (source.project, "Quelle", "unbekannt", "mittel")
        )
        if source.authors:  # materials name their authors; wiki projects credit their community
            authors = ", ".join(plain_label(author) for author in source.authors)
        title = plain_label(source.title)
        stand = f", Stand des Archivs {plain_label(source.zim_date)}" if source.zim_date else ""
        # the archives are free to read, a material with a free licence as well; of another nothing says it
        access = "[Zugang: frei] " if freely_accessible(source.license) else ""
        facet = f" {access}[Vertrauensgrad: {trust}]" if facets_visible else ""
        lines.append(f"- **{web_link(title, source.url)}** — {label}, {form}{stand}{facet}")
        lines.append(
            f"  - TULLU: Titel „{title}“ · Urheber {authors} · Lizenz {plain_label(source.license)} · "
            f"Link {plain_label(source.url)} · Ursprungsort {label}"
        )
        if source.zim_file:
            entry = f" · Eintrag {code_span(source.entry_path)}" if source.entry_path else ""
            lines.append(f"  - Archiv: {code_span(source.zim_file)}{entry}")

    if citations:
        lines += [
            "",
            "### Belegstellen",
            "",
            "| Beleg | Quelle | Abschnitt | Textauszug |",
            "| :---: | :--- | :--- | :--- |",
        ]
        for cit in citations:
            snippet = " ".join(cit.snippet.split())
            if len(snippet) > 140:
                snippet = snippet[:137] + "…"  # cut before the escapes, so none is cut in half
            source_link = cell_link(table_cell(cit.source_title), cit.source_url)
            lines.append(
                f"| [{cit.number}] | {source_link} | {table_cell(cit.section_heading)} | {table_cell(snippet)} |"
            )

    references = [line for source in sources for line in source.reference_lines]
    references = list(dict.fromkeys(references))[:15]
    if references:
        lines += ["", "### Weiterführende Quellen aus den Artikeln", ""]
        lines += [f"- {table_cell(ref)}" for ref in references]

    used = _enumerate(sorted({plain_label(source.license) for source in sources}))
    licences = f" ({used})" if used else ""
    lines += [
        "",
        f"> **Lizenz- und Attributionshinweis:** Teil 1 übernimmt Absätze aus den oben genannten Quellen{licences}; "
        "Urheber, Lizenz und Link stehen je Quelle in der Liste. Die Texte wurden ausgewählt, gekürzt und neu "
        f"gegliedert; die Belegstellen nennen die Herkunft jedes Absatzes. {_rights(restricted)}",
    ]
    return "\n".join(lines)


def _rights(restricted: Sequence[Source]) -> str:
    """Under which licence part 1 stands: CC BY-SA 4.0, except for the paragraphs of sources without a free licence."""
    if not restricted:
        return "Teil 1 steht unter CC BY-SA 4.0."
    named = [f"„{plain_label(source.title)}“ ({plain_label(source.license)})" for source in restricted]
    if len(named) > MAX_NAMED_RESTRICTED:
        named = [*named[:MAX_NAMED_RESTRICTED], f"{len(named) - MAX_NAMED_RESTRICTED} weitere Quellen"]
    verb = "trägt" if len(restricted) == 1 else "tragen"
    return (
        f"{_enumerate(named)} {verb} keine freie Lizenz: Für Absätze daraus gelten die Bedingungen der Quelle, für den "
        "übrigen Text von Teil 1 CC BY-SA 4.0."
    )
