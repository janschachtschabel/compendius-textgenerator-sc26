"""Topic normalisation (PLAN.md 4.2, decision D12).

Compendia describe world knowledge across all educational levels, so grade, level, audience
and subject qualifiers are stripped from the input and kept only as context:
"Optik in Klasse 7" -> topic "Optik", context ["Klasse 7"].
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SUBJECTS = {
    "physik",
    "chemie",
    "biologie",
    "mathematik",
    "mathe",
    "deutsch",
    "englisch",
    "geschichte",
    "geographie",
    "geografie",
    "erdkunde",
    "politik",
    "sozialkunde",
    "gemeinschaftskunde",
    "informatik",
    "musik",
    "kunst",
    "sport",
    "religion",
    "ethik",
    "philosophie",
    "wirtschaft",
    "technik",
    "latein",
    "französisch",
    "spanisch",
    "sachunterricht",
    "medienbildung",
    "pädagogik",
    "psychologie",
    "astronomie",
    "nawi",
    "naturwissenschaften",
}

_LEVEL = (
    r"(?:Grundschule|Primarstufe|Primarbereich|Unterstufe|Mittelstufe|Oberstufe|"
    r"Sekundarstufe\s*(?:II|I|1|2)|Sek\.?\s*(?:II|I|1|2)|Gymnasium|Realschule|Hauptschule|Oberschule|"
    r"Gesamtschule|Berufsschule|Berufsbildung|Hochschule|Universität|Studium|Kita|Kindergarten|"
    r"Elementarbereich|Erwachsenenbildung)"
)
_GRADE = (
    r"(?:Klassenstufe|Klassenstufen|Klasse|Klassen|Jahrgangsstufe|Jahrgang|Jgst\.?|Stufe)"
    r"\s*\d{1,2}(?:\s*(?:-|–|bis|/)\s*\d{1,2})?"
)
_AUDIENCE = (
    r"(?:Kinder|Schülerinnen und Schüler|Schüler(?:innen)?|Lernende|Lehrkräfte|Lehrer(?:innen)?|"
    r"Anfänger(?:innen)?|Einsteiger(?:innen)?|Fortgeschrittene|Studierende|Auszubildende|Azubis)"
)
_LEAD_IN = r"(?:in|an|ab|bis|für|fuer|zum|zur|im)\s+(?:der|die|das|den|dem|einer|einem)?\s*"

_QUALIFIERS: list[re.Pattern[str]] = [
    re.compile(rf"\(\s*(?:{_LEAD_IN})?(?:{_GRADE}|{_LEVEL}|{_AUDIENCE})\s*\)", re.IGNORECASE),
    re.compile(rf"\b(?:{_LEAD_IN})?{_GRADE}\b", re.IGNORECASE),
    re.compile(rf"\b(?:{_LEAD_IN})?{_LEVEL}\b", re.IGNORECASE),
    re.compile(rf"\b(?:{_LEAD_IN}){_AUDIENCE}\b", re.IGNORECASE),
]
_LEAD_IN_RE = re.compile(rf"^{_LEAD_IN}", re.IGNORECASE)
_PREFIX_RE = re.compile(r"^\s*([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß\- ]{1,30}?)\s*:\s*(.+)$")
_GENERIC_PREFIXES = {"thema", "sammlung", "themenseite", "kompendium", "titel", "topic"}


@dataclass
class NormalizedTopic:
    query: str
    topic: str
    context: list[str] = field(default_factory=list)
    subject: str | None = None


def _clean_context(text: str) -> str:
    text = text.strip().strip("()").strip()
    text = _LEAD_IN_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_topic(raw: str) -> NormalizedTopic:
    """Strip level, grade, audience and subject qualifiers; keep them as context."""
    query = raw.strip()
    text = query
    context: list[str] = []
    subject: str | None = None

    prefix_match = _PREFIX_RE.match(text)
    if prefix_match:
        prefix, rest = prefix_match.group(1).strip(), prefix_match.group(2).strip()
        if prefix.lower() in _GENERIC_PREFIXES:
            text = rest
        elif prefix.lower() in _SUBJECTS:
            subject = prefix
            context.append(f"Fach {prefix}")
            text = rest

    for pattern in _QUALIFIERS:
        for match in pattern.finditer(text):
            label = _clean_context(match.group(0))
            if label and label not in context:
                context.append(label)
        text = pattern.sub(" ", text)

    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" -–:,;/")
    if not text:
        text = query
    return NormalizedTopic(query=query, topic=text, context=context, subject=subject)


def topic_stem(title: str) -> str:
    """Short lowercase stem of the first title word, used for cheap topicality checks.

    "Optik" -> "opti" (matches "optisch", "Optiker"), "Demokratie" -> "demokrati".
    """
    word = re.sub(r"\s*\(.*\)$", "", title).strip().split(" ")[0].lower()
    return word[:-1] if len(word) >= 5 else word
