"""Generated block: glossary from lead sentences of corpus articles (no invented definitions)."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.domain.models import Source
from app.knowledge.segmentation import split_sentences
from app.synthesis.safe_markdown import cell_link, plain_label, table_cell

MAX_ENTRIES = 20


def _definition(source: Source) -> str | None:
    lead = source.lead_text
    if not lead:
        return None
    for sentence in split_sentences(lead):
        # "[^()]", not "[^)]": over a run of "(" without ")" every try read to the end, 0.22 s for 20,000 characters
        # of a material description (audit 2026-09-28, PE-09)
        clean = re.sub(r"\s*\([^()]*\)", "", sentence).strip()
        clean = re.sub(r"\s+", " ", clean)
        if len(clean) >= 30 and re.search(
            r"\b(ist|sind|bezeichnet|bezeichnen|nennt man|versteht man|war|gilt)\b", clean
        ):
            return clean if len(clean) <= 320 else clean[:317] + "…"
    return None


def build_glossary(topic: str, primary: Source | None, sources: Sequence[Source], aliases: Sequence[str]) -> str:
    lines = [
        f"Begriffe rund um **{plain_label(topic)}** mit der jeweils ersten Definitionsaussage aus dem Artikel. "
        "Das Glossar ist der einzige Ort für Definitionen im Kompendium.",
        "",
        "| Begriff | Definition | Relation | Beleg |",
        "| :--- | :--- | :--- | :--- |",
    ]
    entries: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    if primary is not None:
        definition = _definition(primary)
        if definition:
            entries.append(
                (primary.title, definition, "skos:prefLabel", cell_link(table_cell(primary.title), primary.url))
            )
            seen.add(primary.title.lower())
        for alias in aliases:
            if alias.lower() not in seen and alias.lower() != primary.title.lower():
                entries.append(
                    (
                        alias,
                        f"Alternativbezeichnung für {primary.title}.",
                        "skos:altLabel",
                        cell_link(table_cell(primary.title), primary.url),
                    )
                )
                seen.add(alias.lower())

    stem = topic.lower()[:5]
    for source in sources:
        if source.is_primary or source.title.lower() in seen:
            continue
        definition = _definition(source)
        if not definition:
            continue
        relation = "skos:narrower" if stem and stem in source.title.lower() else "skos:related"
        entries.append((source.title, definition, relation, cell_link(table_cell(source.title), source.url)))
        seen.add(source.title.lower())
        if len(entries) >= MAX_ENTRIES:
            break

    if not entries:
        return ""
    for term, definition, relation, source_link in sorted(
        entries, key=lambda e: (e[2] != "skos:prefLabel", e[0].lower())
    ):
        lines.append(f"| **{table_cell(term)}** | {table_cell(definition)} | `{relation}` | {source_link} |")
    return "\n".join(lines)
