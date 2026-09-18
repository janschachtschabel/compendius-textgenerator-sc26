"""Generated block: sources with provenance, TULLU attribution and the citation table."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.models import Citation, Source

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


def _cell(text: str) -> str:
    return text.replace("|", "–").replace("\n", " ").strip()


def build_sources_section(sources: Sequence[Source], citations: Sequence[Citation], facets_visible: bool) -> str:
    lines: list[str] = ["Die Inhalte von Teil 1 stammen aus folgenden freien Wissensbeständen:", ""]
    for source in sources:
        label, form, authors, trust = PROJECT_LABELS.get(
            source.project, (source.project, "Quelle", "unbekannt", "mittel")
        )
        if source.authors:  # materials name their authors; wiki projects credit their community
            authors = ", ".join(source.authors)
        stand = f", Stand des Archivs {source.zim_date}" if source.zim_date else ""
        facet = f" [Zugang: frei] [Vertrauensgrad: {trust}]" if facets_visible else ""
        lines.append(f"- **[{source.title}]({source.url})** — {label}, {form}{stand}{facet}")
        lines.append(
            f"  - TULLU: Titel „{source.title}“ · Urheber {authors} · Lizenz {source.license} · "
            f"Link {source.url} · Ursprungsort {label}"
        )
        if source.zim_file:
            lines.append(
                f"  - Archiv: `{source.zim_file}`" + (f" · Eintrag `{source.entry_path}`" if source.entry_path else "")
            )

    if citations:
        lines += [
            "",
            "### Belegstellen",
            "",
            "| Beleg | Quelle | Abschnitt | Textauszug |",
            "| :---: | :--- | :--- | :--- |",
        ]
        for cit in citations:
            snippet = _cell(cit.snippet)
            if len(snippet) > 140:
                snippet = snippet[:137] + "…"
            source_link = f"[{_cell(cit.source_title)}]({cit.source_url})"
            lines.append(f"| [{cit.number}] | {source_link} | {_cell(cit.section_heading)} | {snippet} |")

    references = [line for source in sources for line in source.reference_lines]
    references = list(dict.fromkeys(references))[:15]
    if references:
        lines += ["", "### Weiterführende Quellen aus den Artikeln", ""]
        lines += [f"- {_cell(ref)}" for ref in references]

    used = _enumerate(sorted({source.license for source in sources}))
    lines += [
        "",
        f"> **Lizenz- und Attributionshinweis:** Teil 1 übernimmt Absätze aus den oben genannten Quellen ({used}); "
        "Urheber, Lizenz und Link stehen je Quelle in der Liste. Die Texte wurden ausgewählt, gekürzt und neu "
        "gegliedert; die Belegstellen nennen die Herkunft jedes Absatzes. Teil 1 steht unter CC BY-SA 4.0.",
    ]
    return "\n".join(lines)
