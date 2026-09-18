"""Segmentation of sources into chunks (PLAN.md 4.3) and sentence splitting."""

from __future__ import annotations

import re

from app.domain.models import ArticleSection, Chunk, ChunkKind, Paragraph, Source
from app.matching.base import tokenize
from app.matching.lexicon import HeadingLexicon

MIN_TEXT_CHARS = 40
LEAD_MERGE_CHARS = 1100

# Boilerplate that appears in article bodies of the supported projects (independent of topic).
_BOILERPLATE = (
    "auf spenden angewiesen",
    "klexikon.de ist",
    "klexikon wird gefördert",
    "klexikon-botschafter",
    "schreib uns gerne",
    "dieser artikel wurde von",
    "für die mediendateien können zusätzliche bedingungen",
    "spendenaufruf",
    "creative commons attribution-share alike",
    "ist nach einschätzung seiner autoren zu",
    "% fertig",
    "dieses buch steht im regal",
    "status des buches",
    "wikibooks-regal",
    "dieser artikel oder abschnitt bedarf einer überarbeitung",
    "dieser artikel behandelt",
    "ist eine begriffsklärungsseite",
)

_ABBREVIATIONS = (
    "z. B.", "z.B.", "u. a.", "u.a.", "bzw.", "ca.", "Nr.", "Jh.", "v. Chr.", "n. Chr.", "usw.", "etc.", "Dr.",
    "Prof.", "St.", "vgl.", "d. h.", "d.h.", "u. U.", "sog.", "ggf.", "evtl.", "Abb.", "Bd.", "Hrsg.", "Aufl.",
    "S.", "geb.", "gest.", "Mio.", "Mrd.", "Tsd.", "Std.", "Min.", "Sek.", "Jan.", "Feb.", "Okt.", "Nov.", "Dez.",
    "engl.", "lat.", "griech.", "frz.", "ital.", "span.", "österr.", "schweiz.", "dt.", "ehem.", "inkl.", "zzgl.",
    "bspw.", "einschl.", "insbes.", "bzgl.", "i. d. R.", "i.d.R.", "u. ä.", "o. ä.", "z. T.", "z.T.", "allg.", "Abs.",
    "Kap.", "Tab.", "zzt.", "sogen.", "ausschl.", "urspr.", "entspr.", "zuzügl.", "abzügl.",
)  # fmt: skip
# Not listed on purpose: "vs." and "Art." also end ordinary words at a sentence end ("des Objektivs.", "eine Art.").
_ORDINAL_FOLLOWERS = (
    r"Jahrhundert|Jahrhunderts|Jh\.|Jahrtausend|Jahrtausends|Klasse|Auflage|Kapitel|Band|Teil|Buch|Akt|Satz|"
    r"Sinfonie|Symphonie|Legion|Armee|Dynastie|Konzil|Weltkrieg|Lebensjahr|Platz|Rang|Stelle|Mal|Tag|Monat|Woche|"
    r"Jahr|Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|Halbjahr|Quartal|"
    r"Jahrgangsstufe|Schuljahr|Semester|Stunde|Generation|Version|Ausgabe"
)
_ORDINAL_RE = re.compile(rf"\b(\d{{1,2}})\.(?=\s+(?:{_ORDINAL_FOLLOWERS})\b)")
_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ„\"(\[0-9])")
_PLACEHOLDER = "․"  # one dot leader, restored after splitting
# An initial in a name ("Max M. Mustermann", "M. M. Mustermann"): a single capital before another initial or a
# content word.
# A function word after it ("Vitamin C. Die …") marks a real sentence end; ``tokenize`` drops those. The next
# initial may already carry the placeholder, because "S." is also a listed abbreviation.
_INITIAL_RE = re.compile(rf"\b([A-ZÄÖÜ])\.(?=\s+(?:[A-ZÄÖÜ][.{_PLACEHOLDER}]|([A-ZÄÖÜ][\w-]+)))")


def _protect_initial(match: re.Match[str]) -> str:
    next_word = match.group(2)
    if next_word is not None and not tokenize(next_word):
        return match.group(0)  # "… Vitamin C. Die …": the sentence ends here
    return f"{match.group(1)}{_PLACEHOLDER}"


def ends_with_abbreviation(text: str) -> bool:
    """True when the text ends with a known abbreviation, so the full stop is not a sentence end."""
    return text.rstrip().endswith(_ABBREVIATIONS)


def split_sentences(text: str) -> list[str]:
    """Split German prose into sentences while protecting abbreviations and ordinal numbers."""
    protected = re.sub(r"\s+", " ", text).strip()
    for abbr in _ABBREVIATIONS:
        protected = protected.replace(abbr, abbr.replace(".", _PLACEHOLDER))
    protected = _ORDINAL_RE.sub(lambda m: f"{m.group(1)}{_PLACEHOLDER}", protected)
    protected = _INITIAL_RE.sub(_protect_initial, protected)
    protected = re.sub(r"(\d)\.(\d)", rf"\1{_PLACEHOLDER}\2", protected)
    parts = _SPLIT_RE.split(protected)
    return [p.replace(_PLACEHOLDER, ".").strip() for p in parts if p.strip()]


_POINTER_RE = re.compile(r"^(→|siehe auch:|hauptartikel:)", re.IGNORECASE)
_FIGURE_RE = re.compile(r"^(in|im) (figur|bild|abbildung|grafik|tabelle|diagramm)\b", re.IGNORECASE)
CAPTION_MAX_CHARS = 100


def _is_fragment(text: str) -> bool:
    """Formula intros ("… beträgt:"), captions of removed formulas and figure references."""
    stripped = text.strip()
    if stripped.endswith(":"):
        return True
    if len(stripped) < CAPTION_MAX_CHARS and not stripped.endswith((".", "!", "?", "“", '"', ")")):
        return True
    return bool(_FIGURE_RE.match(stripped))


def _is_boilerplate(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _BOILERPLATE) or text.startswith(("↑", "^", "[↑]")):
        return True
    return bool(_POINTER_RE.match(text.strip()))  # "→ Hauptartikel: …", "Siehe auch: …" carry no content


def _reference_lines(section: ArticleSection) -> list[str]:
    lines: list[str] = []
    for paragraph in section.paragraphs:
        for line in paragraph.text.splitlines():
            clean = line.strip(" -•*")
            if len(clean) >= 12 and not _is_boilerplate(clean):
                lines.append(clean)
    return lines


def _relation_titles(section: ArticleSection) -> list[str]:
    titles: list[str] = []
    for paragraph in section.paragraphs:
        for line in paragraph.text.splitlines():
            clean = re.split(r"\s+[–-]\s+|:", line.strip(" -•*"))[0].strip()
            if 2 <= len(clean) <= 80:
                titles.append(clean)
    return titles


def _introduces_list(text: str) -> bool:
    """A colon, or a short line without terminal punctuation ("Das Arbeitsfeld umfasst")."""
    stripped = text.rstrip()
    return stripped.endswith(":") or (len(stripped) < 160 and not stripped.endswith((".", "!", "?", "…")))


def _merge_intro_lists(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """A paragraph that introduces the list following it is kept together with that list."""
    merged: list[Paragraph] = []
    index = 0
    while index < len(paragraphs):
        current = paragraphs[index]
        following = paragraphs[index + 1] if index + 1 < len(paragraphs) else None
        if (
            current.kind is ChunkKind.TEXT
            and _introduces_list(current.text)
            and following is not None
            and following.kind is ChunkKind.LIST
        ):
            items = [line.strip(" -•*") for line in following.text.splitlines() if line.strip()]
            joined = current.text.rstrip() + " " + "; ".join(items)
            if not joined.endswith((".", "!", "?")):
                joined += "."
            merged.append(Paragraph(kind=ChunkKind.TEXT, text=joined))
            index += 2
            continue
        merged.append(current)
        index += 1
    return merged


def _merge_lead(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """Keep the defining lead paragraphs of the primary article together."""
    merged: list[Paragraph] = []
    block: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if paragraph.kind is ChunkKind.TEXT and not merged and size + len(paragraph.text) <= LEAD_MERGE_CHARS:
            block.append(paragraph.text)
            size += len(paragraph.text)
            continue
        if block and not merged:
            merged.append(Paragraph(kind=ChunkKind.TEXT, text="\n\n".join(block)))
        merged.append(paragraph)
    if block and not merged:
        merged.append(Paragraph(kind=ChunkKind.TEXT, text="\n\n".join(block)))
    return merged


def segment_source(source: Source, lexicon: HeadingLexicon) -> list[Chunk]:
    """Turn a parsed source into chunks; excluded sections feed references and relations."""
    chunks: list[Chunk] = []
    position = 0
    for section in source.sections:
        if lexicon.is_excluded(section.path):
            source.reference_lines.extend(_reference_lines(section))
            continue
        if lexicon.is_relation(section.path):
            source.relation_titles.extend(_relation_titles(section))
            continue

        paragraphs = [p for p in section.paragraphs if p.text.strip() and not _is_boilerplate(p.text)]
        paragraphs = _merge_intro_lists(paragraphs)
        paragraphs = [p for p in paragraphs if len(p.text.strip()) >= MIN_TEXT_CHARS]
        paragraphs = [p for p in paragraphs if p.kind is not ChunkKind.TEXT or not _is_fragment(p.text)]
        if section.is_lead and source.is_primary:
            paragraphs = _merge_lead(paragraphs)
        if not paragraphs:
            continue

        lexicon_slot = lexicon.classify(section.path) if section.path else None
        for index, paragraph in enumerate(paragraphs):
            is_lead = section.is_lead and source.is_primary and index == 0
            chunks.append(
                Chunk(
                    chunk_id=f"{source.source_id}:c{position:03d}",
                    source_id=source.source_id,
                    heading=section.heading or "Einleitung",
                    heading_path=list(section.path),
                    heading_level=section.level,
                    is_lead=is_lead,
                    is_section_lead=(section.level == 2 and index == 0),
                    kind=paragraph.kind,
                    text=paragraph.text.strip(),
                    position=position,
                    lexicon_slot=lexicon_slot,
                )
            )
            position += 1

    source.reference_lines = list(dict.fromkeys(source.reference_lines))[:40]
    source.relation_titles = list(dict.fromkeys(source.relation_titles))[:40]
    return chunks
