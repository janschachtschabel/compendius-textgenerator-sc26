"""German prose as the service reads it: its words without stopwords, and its sentences with abbreviations, ordinals
and initials protected. Below every part that reads text (knowledge, matching, sources, synthesis)."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-zäöüß0-9]+")
_STOPWORDS = frozenset(
    """
    der die das des dem den ein eine einer eines einem einen und oder aber auch als bei mit ohne von vom zu zum zur
    für fuer im in ins an am auf aus nach über unter vor durch gegen um bis seit wird werden wurde wurden ist sind war
    waren sein hat haben hatte hatten kann können konnte nicht nur noch sich so wie was wer wo dass ob es er sie wir ihr
    man diese dieser dieses diesen jene alle allen alles andere anderen mehr sehr etwa z b zb bzw sowie dabei dazu
    daher dann dort hier heute schon bereits sowohl weder noch zwischen während wegen trotz statt keine keinen reine
    reinen baustein bausteine siehe
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens without stopwords (German)."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2 and t not in _STOPWORDS]


_ABBREVIATIONS = (
    "z. B.", "z.B.", "u. a.", "u.a.", "bzw.", "ca.", "Nr.", "Jh.", "v. Chr.", "n. Chr.", "usw.", "etc.", "Dr.",
    "Prof.", "St.", "vgl.", "d. h.", "d.h.", "u. U.", "sog.", "ggf.", "evtl.", "Abb.", "Bd.", "Hrsg.", "Aufl.",
    "S.", "geb.", "gest.", "Mio.", "Mrd.", "Tsd.", "Std.", "Min.", "Sek.", "Jan.", "Feb.", "Okt.", "Nov.", "Dez.",
    "engl.", "lat.", "griech.", "frz.", "ital.", "span.", "österr.", "schweiz.", "dt.", "ehem.", "inkl.", "zzgl.",
    "bspw.", "einschl.", "insbes.", "bzgl.", "i. d. R.", "i.d.R.", "u. ä.", "o. ä.", "z. T.", "z.T.", "allg.", "Abs.",
    "Kap.", "Tab.", "zzt.", "sogen.", "ausschl.", "urspr.", "entspr.", "zuzügl.", "abzügl.",
)  # fmt: skip
# Not listed on purpose: "vs." and "Art." also end ordinary words at a sentence end ("des Objektivs.", "eine Art.").
# An abbreviation only where no letter stands before it: "Hauptstadt." ends in "dt.", "Kapital." in "ital." and
# "GPS." in "S.", and none of them ended its sentence (audit 2026-09-27, KO-10). The longest first, so "u. a."
# wins over any shorter one at the same place.
_ABBREVIATION_RE = re.compile(
    r"(?<![^\W\d_])(?:" + "|".join(re.escape(a) for a in sorted(_ABBREVIATIONS, key=len, reverse=True)) + ")"
)
_ABBREVIATION_END_RE = re.compile(_ABBREVIATION_RE.pattern + r"\Z")
_ABBREVIATION_TAIL = 1 + max(len(a) for a in _ABBREVIATIONS)  # the longest one and the character before it
_ORDINAL_FOLLOWERS = (
    r"Jahrhundert|Jahrhunderts|Jahrtausend|Jahrtausends|Klasse|Auflage|Kapitel|Band|Teil|Buch|Akt|Satz|"
    r"Sinfonie|Symphonie|Legion|Armee|Dynastie|Konzil|Weltkrieg|Lebensjahr|Platz|Rang|Stelle|Mal|Tag|Monat|Woche|"
    r"Jahr|Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|Halbjahr|Quartal|"
    r"Jahrgangsstufe|Schuljahr|Semester|Stunde|Generation|Version|Ausgabe"
)
# "Jh." ends in its dot, after which no word boundary follows: it stands outside the words that need one
_ORDINAL_RE = re.compile(rf"\b(\d{{1,2}})\.(?=\s+(?:(?:{_ORDINAL_FOLLOWERS})\b|Jh\.))")
_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ„\"(\[0-9])")
# A protected full stop while the text is split, restored afterwards: a sign of the private use area, which prose
# does not hold. It was a dot leader (U+2024), and one the paragraph held became a full stop as well (audit
# 2026-09-28, TE-12).
_PLACEHOLDER = chr(0xE000)
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
    return _ABBREVIATION_END_RE.search(text.rstrip()[-_ABBREVIATION_TAIL:]) is not None


def split_sentences(text: str) -> list[str]:
    """Split German prose into sentences while protecting abbreviations and ordinal numbers."""
    protected = re.sub(r"\s+", " ", text).strip()
    # Ordinals first: the abbreviations take the dot of the "Jh." an ordinal is known by ("im 18. Jh.", review of
    # 2026-10-08)
    protected = _ORDINAL_RE.sub(lambda m: f"{m.group(1)}{_PLACEHOLDER}", protected)
    protected = _ABBREVIATION_RE.sub(lambda m: m.group(0).replace(".", _PLACEHOLDER), protected)
    protected = _INITIAL_RE.sub(_protect_initial, protected)
    protected = re.sub(r"(\d)\.(\d)", rf"\1{_PLACEHOLDER}\2", protected)
    parts = _SPLIT_RE.split(protected)
    return [p.replace(_PLACEHOLDER, ".").strip() for p in parts if p.strip()]
