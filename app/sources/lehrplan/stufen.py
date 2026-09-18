"""Educational level ladders and the word-boundary noise rule (PLAN.md 5.3, 5.4).

Several state graphs assert neither Schulstufe nor Jahrgangsstufe. Both grouping keys are therefore
resolved through a documented ladder, and every result carries its provenance so the rendering can
say whether a level came from the data or was derived from a curriculum title. Ported from the
``optik_uebersicht`` prototype (mem-schule-optik), including its tests.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.sources.lehrplan.store import LehrplanRecord

PRIMAR = "Primarstufe"
SEK_I = "Sekundarstufe I"
SEK_II = "Sekundarstufe II"
OHNE_STUFE = "Ohne Stufenzuordnung"
OHNE_KLASSE = "Ohne Klassenstufenangabe"
STUFEN_ORDER = (PRIMAR, SEK_I, SEK_II, OHNE_STUFE)

SOURCE_NODE = "Daten (Knoten)"
SOURCE_LEHRPLAN = "Daten (Lehrplan)"
SOURCE_GRADE = "abgeleitet aus Jahrgangsstufe"
SOURCE_TITLE = "abgeleitet aus Lehrplantitel"
SOURCE_NONE = "nicht bestimmbar"

# Ontology labels ("Sekundarbereich I") and curriculum titles ("Sekundarstufe II")
_STUFEN_LABELS = (
    (re.compile(r"primar|grundschul", re.I), PRIMAR),
    (re.compile(r"sekundar(bereich|stufe)?\s*(II|2)\b", re.I), SEK_II),
    (re.compile(r"sekundar(bereich|stufe)?\s*(I|1)\b", re.I), SEK_I),
)
_TITEL_SEK_II = re.compile(
    r"oberstufe|sekundarstufe\s*(II|2)|leistungsfach|fachoberschule|berufsoberschule|berufliches\s+gymnasium|"
    r"gymnasiale\s+oberstufe|abitur|qualifikationsphase|einführungsphase",
    re.I,
)
_TITEL_SEK_I = re.compile(
    r"oberschule|mittelschule|realschule|hauptschule|förderschwerpunkt|sekundarstufe\s*(I|1)\b|"
    r"wirtschaftsschule|gesamtschule",
    re.I,
)
_TITEL_PRIMAR = re.compile(r"grundschule|primarstufe", re.I)
# Any standalone one- or two-digit number in 1..13 counts as a grade ("Physik 7-9/10" -> 7, 9, 10).
_GRADE = re.compile(r"\b(\d{1,2})\b")
_WORD = r"[\wäöüÄÖÜß]"


@dataclass(frozen=True)
class Resolved:
    value: str
    source: str

    @property
    def from_data(self) -> bool:
        return self.source.startswith("Daten")


def is_noise(label: str, keywords: Sequence[str]) -> bool:
    """True when every matching keyword sits buried inside a longer word.

    German compounds carry the topic word at either end ("Lichtbrechung", "Kernphysik") and are on
    topic. Only a keyword with word material on both sides is noise: "Licht" in
    "Wahlpflichtlernbereich", "Strahl" in "Wärmestrahlung".
    """
    contained = [word for word in keywords if word and re.search(re.escape(word), label, re.I)]
    if not contained:
        return False
    return not any(
        re.search(rf"(?<!{_WORD}){re.escape(word)}|{re.escape(word)}(?!{_WORD})", label, re.I) for word in contained
    )


def grades_in(text: str) -> list[int]:
    """Grade numbers mentioned in a label or curriculum title."""
    return [int(match.group(1)) for match in _GRADE.finditer(text) if 1 <= int(match.group(1)) <= 13]


def _stufe_from_label(text: str) -> str | None:
    for pattern, name in _STUFEN_LABELS:
        if pattern.search(text):
            return name
    return None


def _stufe_from_grade(grade: int) -> str:
    if grade <= 4:
        return PRIMAR
    if grade <= 10:
        return SEK_I
    return SEK_II


def resolve_schulstufe(node_grades: Sequence[str], lehrplan: LehrplanRecord) -> Resolved:
    """Ladder: asserted Schulstufe of the curriculum, then a grade (node, then curriculum), then the title."""
    for label in lehrplan.schulstufen:
        name = _stufe_from_label(label)
        if name:
            return Resolved(name, SOURCE_LEHRPLAN)
    for grades in (node_grades, lehrplan.jahrgangsstufen):
        numbers = [grade for label in grades for grade in grades_in(label)]
        if numbers:
            return Resolved(_stufe_from_grade(min(numbers)), SOURCE_GRADE)
    title = lehrplan.label
    if _TITEL_SEK_II.search(title):
        return Resolved(SEK_II, SOURCE_TITLE)
    if _TITEL_PRIMAR.search(title):
        return Resolved(PRIMAR, SOURCE_TITLE)
    if _TITEL_SEK_I.search(title):
        return Resolved(SEK_I, SOURCE_TITLE)
    numbers = grades_in(title)
    if numbers:
        return Resolved(_stufe_from_grade(min(numbers)), SOURCE_TITLE)
    return Resolved(OHNE_STUFE, SOURCE_NONE)


def resolve_klassenstufe(node_grades: Sequence[str], lehrplan: LehrplanRecord) -> Resolved:
    """Ladder: grades asserted on the node, then on the curriculum, then a range parsed from the title."""
    if node_grades:
        return Resolved(" / ".join(sorted(set(node_grades), key=klassenstufe_sort_key)), SOURCE_NODE)
    if lehrplan.jahrgangsstufen:
        return Resolved(" / ".join(sorted(set(lehrplan.jahrgangsstufen), key=klassenstufe_sort_key)), SOURCE_LEHRPLAN)
    numbers = grades_in(lehrplan.label)
    if numbers:
        low, high = min(numbers), max(numbers)
        name = f"Klassenstufe {low}" if low == high else f"Klassenstufen {low}–{high}"
        return Resolved(name, SOURCE_TITLE)
    return Resolved(OHNE_KLASSE, SOURCE_NONE)


def klassenstufe_sort_key(name: str) -> tuple[int, str]:
    if name == OHNE_KLASSE:
        return (99, name)
    numbers = grades_in(name)
    return (min(numbers) if numbers else 98, name)
