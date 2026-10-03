"""Topic normalisation (PLAN.md 4.2, decision D12).

Compendia describe world knowledge across all educational levels, so grade, level, audience
and subject qualifiers are stripped from the input and kept only as context:
"Optik in Klasse 7" -> topic "Optik", context ["Klasse 7"].
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# A level, a grade or an audience. Such a word names things of its own as well - "Universität Heidelberg",
# "Geschichte der Universität", "Humboldt-Universität zu Berlin", "Stufe 1 der Energiewende" - so it only counts as a
# qualifier where it is added to a topic (_QUALIFIERS).
_LEVEL = (
    r"(?:Grundschule|Primarstufe|Primarbereich|Unterstufe|Mittelstufe|Oberstufe|Gymnasium|Realschule|Hauptschule|"
    r"Oberschule|Gesamtschule|Berufsschule|Berufsbildung|Hochschule|Universität|Studium|Kita|Kindergarten|"
    r"Elementarbereich|Erwachsenenbildung)"
)
_STAGE = r"(?:Sekundarstufe\s*(?:II|I|1|2)|Sek\.?\s*(?:II|I|1|2))"
_GRADE = (
    r"(?:Klassenstufe|Klassenstufen|Klasse|Klassen|Jahrgangsstufe|Jahrgang|Jgst\.?|Stufe)"
    r"\s*\d{1,2}(?:\s*(?:-|–|bis|/)\s*\d{1,2})?"
)
_AUDIENCE = (
    r"(?:Kinder|Schülerinnen und Schüler|Schüler(?:innen)?|Lernende|Lehrkräfte|Lehrer(?:innen)?|"
    r"Anfänger(?:innen)?|Einsteiger(?:innen)?|Fortgeschrittene|Studierende|Auszubildende|Azubis)"
)
_LEAD_IN = r"(?:in|an|ab|bis|für|fuer|zum|zur|im)\s+(?:der|die|das|den|dem|einer|einem)?\s*"
_QUALIFIER = rf"(?:{_GRADE}|{_STAGE}|{_LEVEL}|{_AUDIENCE})"
# An audience word counts only with a lead-in or in parentheses, as it always did: "Kinder, Küche, Kirche"
_SET_OFF = rf"(?:{_GRADE}|{_STAGE}|{_LEVEL})"
# A colon or a dash sets an addition off - a hyphen only with blanks around it ("Kita-Alltag"); a comma or a slash
# joins a list ("Schule/Hochschule")
_SEPARATOR = r"(?: ?[–—:] ?| - )"

# An addition to a topic, never its head, a word after an article or one joined by a hyphen (audit 2026-09-29, L3):
# in parentheses, after a lead-in, set off at the end or the start, and a grade or a numbered stage after the topic.
# The text has one blank between its words (normalize_topic), so no pattern reads a run of them.
_QUALIFIERS: list[re.Pattern[str]] = [
    re.compile(rf"\(\s*(?:{_LEAD_IN})?{_QUALIFIER}\s*\)", re.IGNORECASE),  # "Optik (Sek I)"
    re.compile(rf"(?<![\w-]){_LEAD_IN}{_QUALIFIER}(?![\w-])", re.IGNORECASE),  # "Optik in Klasse 7"
    re.compile(rf"{_SEPARATOR}{_SET_OFF}$|^{_SET_OFF}{_SEPARATOR}", re.IGNORECASE),  # "Optik – Grundschule"
    re.compile(rf"(?<=[\w)]) (?:{_GRADE}|{_STAGE})$", re.IGNORECASE),  # "Bruchrechnung Klasse 6"
]
_LEAD_IN_RE = re.compile(rf"^{_LEAD_IN}", re.IGNORECASE)
_PREFIX_RE = re.compile(r"^\s*([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß\- ]{1,30}?)\s*:\s*(.+)$")
_GENERIC_PREFIXES = {"thema", "sammlung", "themenseite", "kompendium", "titel", "topic"}
# Two school subjects of the former fixed list that neither the catalogue nor the vocabularies of edu-sharing name
# (D51): a prefix with them still counts as a subject, as it did, so the topic loses it
_SUBJECTS_OUTSIDE_THE_VOCABULARIES = frozenset({"technik", "nawi"})


@dataclass
class NormalizedTopic:
    query: str
    topic: str
    context: list[str] = field(default_factory=list)
    subject: str | None = None


def _clean_context(text: str) -> str:
    text = text.strip(" ()–—:-")
    text = _LEAD_IN_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_topic(raw: str, *, is_subject: Callable[[str], bool] | None = None) -> NormalizedTopic:
    """Strip level, grade, audience and subject qualifiers; keep them as context.

    ``is_subject`` says whether the prefix of "Physik: Optik" names a subject - the service passes its subject
    catalogue (``SubjectCatalog.knows``); without it no prefix counts as one. A list of its own knew 32 subjects and
    missed 33 of the 63 labels and aliases the catalogue names: "Bio: Zelle" became "Bio-Brennstoffzelle" and lost its
    subject (audit 2026-09-28, KO-23).

    A qualifier is an addition to the topic, never part of it (audit 2026-09-29, L3): in parentheses, after a lead-in
    ("in", "für die" ...), set off by a dash or a colon, or a grade or numbered stage right after the topic. A level
    word stripped wherever it stood made "Universität Heidelberg" "Heidelberg", "Geschichte der Universität"
    "Geschichte der" and "Kita-Alltag" "Alltag". Measured on the 1,922 distinct topics and titles the project names -
    the sets of eval/ (gold topics, queries, material titles, 1,662 article titles), the examples of the API, the
    tests, the WLO samples and the cases of the audit: the eight qualifiers stripped before come off alike, from
    "Optik in Klasse 7" to "Bruchrechnung Klasse 6"; 12 topics keep their names, the nine of the audit, "Pädagogische
    Hochschule Schwyz", "Hochschule für Technik Stuttgart" and a material title with "#kita"; eight inputs that are
    nothing but a qualifier ("Klasse 7", "Grundschule") no longer put it into their context; 1,902 come out as before.
    35 of the 94 queries of eval/artikelwahl normalise to an expected article, before as after. A level word right
    after the topic with nothing between ("Optik Grundschule") now stays: none of the 1,922 has that form, and it is
    the form of names ("Pädagogische Hochschule").
    """
    query = raw.strip()
    text = " ".join(query.split())  # one blank between words: no pattern of _QUALIFIERS reads a run of them
    context: list[str] = []
    subject: str | None = None

    prefix_match = _PREFIX_RE.match(text)
    if prefix_match:
        prefix, rest = prefix_match.group(1).strip(), prefix_match.group(2).strip()
        if prefix.lower() in _GENERIC_PREFIXES:
            text = rest
        elif prefix.lower() in _SUBJECTS_OUTSIDE_THE_VOCABULARIES or (is_subject is not None and is_subject(prefix)):
            subject = prefix
            context.append(f"Fach {prefix}")
            text = rest

    for pattern in _QUALIFIERS:
        for match in pattern.finditer(text):
            label = _clean_context(match.group(0))
            if label and label not in context:
                context.append(label)
        text = " ".join(pattern.sub(" ", text).split())

    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" -–:,;/")
    if not text:
        text = query
    return NormalizedTopic(query=query, topic=text, context=context, subject=subject)


def topic_as_asked(normalized: NormalizedTopic) -> str:
    """The topic in the words of the request, its qualifiers kept: "Digitale Bildung in der Grundschule" where the
    archives are searched for "Digitale Bildung" (D12). Only a generic or a subject prefix goes ("Physik: Optik"):
    the subject reaches the prompts on its own. The writer of enrichment=model-knowledge-full writes about this
    (D69), since a text about the archives' topic alone missed requests like "OER-Förderungen"."""
    query = " ".join(normalized.query.split())
    prefix_match = _PREFIX_RE.match(query)
    if prefix_match:
        prefix, rest = prefix_match.group(1).strip(), prefix_match.group(2).strip()
        if prefix.lower() in _GENERIC_PREFIXES or prefix == normalized.subject:
            return rest
    return query or normalized.topic


# An article that opens a title is no stem: "die" from "Die Zauberflöte" is in nearly every German paragraph, and the
# checks that a side article's paragraph is about the topic let everything through (audit 2026-09-27, KO-11)
_LEADING_ARTICLES = frozenset({"der", "die", "das", "des", "dem", "den", "ein", "eine", "einer", "eines", "einem"})


def _title_word(title: str) -> str:
    """The first title word after a leading article, lower case, without a qualifier in parentheses."""
    words = re.sub(r"\s*\(.*\)$", "", title).strip().lower().split(" ")
    return words[1] if len(words) > 1 and words[0] in _LEADING_ARTICLES else words[0]


def topic_stem(title: str) -> str:
    """Short lowercase stem of the first title word after a leading article, used for cheap topicality checks.

    "Optik" -> "opti" (matches "optisch", "Optiker"), "Demokratie" -> "demokrati", "Die Zauberflöte" -> "zauberflöt".
    """
    return word_stem(_title_word(title))


def word_stem(word: str) -> str:
    """The stem of one title word, the one rule of every stem (KO-11): from five letters on without its last."""
    return word[:-1] if len(word) >= 5 else word


_TITLE_WORD = re.compile(r"[a-zäöüß]{4,}")


def title_words(title: str) -> list[str]:
    """The words of a title of at least four letters, lower case, its qualifier in parentheses too ("Linse (Optik)":
    the field names its links), without a leading article ("Eine kleine Nachtmusik")."""
    words = _TITLE_WORD.findall(title.lower())
    return words[1:] if words and words[0] in _LEADING_ARTICLES else words


def title_stems(title: str) -> list[str]:
    """The stem of each word of ``title_words``, for the titles of linked articles: there a stem inside a compound
    counts ("Mondfinsternis" for "Mond"), unlike in a paragraph, which ``TopicMention`` checks (KO-29)."""
    return list(dict.fromkeys(word_stem(word) for word in title_words(title)))


# A title word of at most four letters is its own stem, and a stem that short sits inside common words: "ei" in "ein"
# and "bei". In 979 paragraphs of five foreign Wikipedia articles the stem found the topic Ei 862 times, Eis 313, Rad
# 93 and Ton 62 times; as a word with its endings 0, 10 ("Eisen"), 0 and 0 times. In the topic's own article it still
# finds most paragraphs that name it: 28 of 35 for Ei (34 as a stem), 33 of 69 for Auge (54), 146 of 214 for Mond
# (188); a compound such as "Hühnerei" or "Kochsalz" no longer counts (audit 2026-09-28, KO-29).
SHORT_WORD_CHARS = 4
_ENDINGS = ("e", "en", "er", "ern", "es")  # Eier, Eiern, Eies, Monde, Monden, Rades
_VOWELS = frozenset("aeiouyäöü")


@dataclass(frozen=True)
class TopicMention:
    """How a text mentions a topic, for the cheap checks that a side article or a paragraph is about it: the stem
    inside any word ("demokrati" in "Basisdemokratie"), or a short title word as a word of its own with an ending."""

    stem: str
    word: re.Pattern[str] | None = None  # set for a title word of at most SHORT_WORD_CHARS letters

    @classmethod
    def of(cls, title: str) -> TopicMention:
        word = _title_word(title)
        if not word or len(word) > SHORT_WORD_CHARS:
            return cls(topic_stem(title))
        endings = list(_ENDINGS)
        if word.endswith("e"):
            endings += ["n", "s"]  # Augen, Auges, Seen
        elif word[-1] not in _VOWELS:
            endings.append("s")  # Rads, Tons; not after a vowel, where "ei" with an s is Eis
        return cls(word, re.compile(rf"(?<!\w){re.escape(word)}(?:{'|'.join(endings)})?(?!\w)"))

    def found_in(self, text: str) -> bool:
        """Whether ``text`` mentions the topic; never for a title without a word."""
        if not self.stem:
            return False
        lowered = text.lower()
        return self.stem in lowered if self.word is None else self.word.search(lowered) is not None
