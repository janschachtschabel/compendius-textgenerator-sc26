"""Generated block: sources with provenance, TULLU attribution and the citation table.

Titles, addresses, authors and licences of materials come from a repository anyone may type into, and the
snippets are the sources' words: each goes in through ``plain_label``, and only a web address becomes a link
(audit 2026-09-28, SE-16).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.models import Citation, Source
from app.synthesis.safe_markdown import code_span, plain_label, table_cell, web_link

PROJECT_LABELS = {
    "wikipedia": ("Wikipedia", "Nachschlagewerk", "Wikipedia-Autorinnen und -Autoren", "hoch"),
    "klexikon": ("Klexikon", "Nachschlagewerk (einfache Sprache)", "Klexikon-Autorinnen und -Autoren", "hoch"),
    "wikibooks": ("Wikibooks", "Grundlagenwerk", "Wikibooks-Autorinnen und -Autoren", "mittel"),
    "wikiversity": ("Wikiversity", "Grundlagenwerk (Hochschule)", "Wikiversity-Autorinnen und -Autoren", "mittel"),
    "wlo_material": ("WirLernenOnline", "Sammlung & Archiv", "nicht angegeben", "mittel"),
}


def _enumerate(items: Sequence[str]) -> str:
    """German enumeration: ``A``, ``A und B``, ``A, B und C``."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} und {items[-1]}"


def build_sources_section(sources: Sequence[Source], citations: Sequence[Citation], facets_visible: bool) -> str:
    lines: list[str] = ["Die Inhalte von Teil 1 stammen aus folgenden freien Wissensbeständen:", ""]
    for source in sources:
        label, form, authors, trust = PROJECT_LABELS.get(
            source.project, (source.project, "Quelle", "unbekannt", "mittel")
        )
        if source.authors:  # materials name their authors; wiki projects credit their community
            authors = ", ".join(plain_label(author) for author in source.authors)
        title = plain_label(source.title)
        stand = f", Stand des Archivs {plain_label(source.zim_date)}" if source.zim_date else ""
        facet = f" [Zugang: frei] [Vertrauensgrad: {trust}]" if facets_visible else ""
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
            source_link = web_link(table_cell(cit.source_title), cit.source_url)
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
        "gegliedert; die Belegstellen nennen die Herkunft jedes Absatzes. Teil 1 steht unter CC BY-SA 4.0.",
    ]
    return "\n".join(lines)
