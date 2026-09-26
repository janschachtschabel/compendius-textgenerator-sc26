"""The German words the /qa rule stage knows (D55): what names a time or a place, what points back, what ends a clause.

The parse says which phrase is which constituent; these lists say what a phrase means for a question. They grow
with the texts the stage meets, and for that reason alone they live apart from the rules that read them
(app/synthesis/qa_clause.py, qa_questions.py). Every entry stands for a question the prototype got wrong or missed on
real compendium texts on 2026-09-25.
"""

from __future__ import annotations

import re

YEAR = re.compile(r"^(1[0-9]{3}|20[0-9]{2})$")
_YEAR_BEFORE_STOP = re.compile(r"(\d)\.$")
_WORD = re.compile(r"[\wäöüÄÖÜß]+")
VERBS = frozenset({"VERB", "AUX"})
NOUNS = frozenset({"NOUN", "PROPN"})
ARTICLES = frozenset({"der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "einen", "einem", "eines"})
ACCUSATIVE = frozenset({"den", "einen", "keinen", "diesen"})  # an object that cannot be read as a subject
# Words that point back to what an earlier sentence said; a question holding one cannot be answered on its own
ANAPHORA = frozenset(
    {
        "dies", "diese", "dieser", "dieses", "diesem", "diesen", "jene", "jener", "jenes", "solche", "solcher",
        "solches", "solchen", "derartige", "derartiger", "derartigen", "beide", "beiden", "beider", "letztere",
        "letzterer", "letzteres", "erstere", "ersterer", "genannten", "obige", "folgende", "folgenden", "dessen",
        "deren", "dabei", "dadurch", "dafür", "damit", "darauf", "daraus", "darin", "davon", "dazu", "darüber",
        "darunter", "hierbei", "hierfür", "hierzu", "hier", "dort", "damals", "danach", "zuvor", "anschließend",
        "deshalb", "daher", "deswegen", "ebenfalls", "ebenso", "außerdem", "zudem", "jedoch", "allerdings", "auch",
        "aber", "dennoch", "trotzdem", "wiederum", "hingegen", "dagegen", "demgegenüber", "stattdessen", "vielmehr",
        "also",
        "er", "sie", "es", "ihm", "ihn", "ihr", "ihre", "ihren", "ihrer", "ihrem", "ihres", "sein", "seine",
        "seinen", "seiner", "seinem", "seines",
    }
)  # fmt: skip
# "für den Begriff", "das Wort" without the word it names: which one, the question does not say
_BARE_NAMING = re.compile(
    r"\b(?:der|den|dem|des|das|die)\s+(?:Begriffs?|Wort(?:es|s)?|Bezeichnung|Ausdrucks?|Namens?|Terminus)\b"
    r"(?!\s*[„\"»A-ZÄÖÜ])"
)
TIME_NOUNS = frozenset(
    {
        "jahr", "jahre", "jahren", "jahres", "jahrhundert", "jahrhunderts", "jahrhunderte", "jahrhunderten",
        "jahrzehnt", "jahrzehnts", "jahrzehnte", "jahrzehnten", "jahrtausend", "jahrtausends", "zeit", "zeiten",
        "mittelalter", "mittelalters", "antike", "spätantike", "neuzeit", "kaiserzeit", "epoche", "ära", "anfang",
        "ende", "mitte", "beginn", "januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
        "september", "oktober", "november", "dezember", "frühjahr", "sommer", "herbst", "winter",
    }
)  # fmt: skip
TIME_PREPOSITIONS = frozenset(
    {"im", "in", "um", "seit", "bis", "von", "ab", "nach", "vor", "während", "gegen", "zwischen", "am", "zur", "zum"}
)
SINCE_UNTIL = {"seit": "Seit wann", "bis": "Bis wann"}
PLACE_PREPOSITIONS = {
    "in": "Wo",
    "im": "Wo",
    "an": "Wo",
    "am": "Wo",
    "bei": "Wo",
    "beim": "Wo",
    "auf": "Wo",
    "aus": "Woher",
}
# A verb that says where something is makes a place of a phrase that names no place entity
LOCATION_VERBS = frozenset({"befinden", "liegen", "leben", "wohnen", "vorkommen", "entspringen", "münden"})
LOCATION_PREPOSITIONS = frozenset(
    {"in", "im", "an", "am", "auf", "bei", "beim", "unter", "über", "innerhalb", "außerhalb"}
)
# Heads of phrases that look like places and are none: "im Gegensatz dazu", "im Rahmen", "im Fall der Erde"
ABSTRACT_HEADS = frozenset(
    {
        "gegensatz", "rahmen", "zusammenhang", "fall", "bereich", "sinne", "sinn", "folge", "regel", "grundlage",
        "hinblick", "bezug", "vergleich", "laufe", "form", "art", "weise", "teil", "praxis", "theorie",
    }
)  # fmt: skip
# A subject that names a word ("Das Wort „Vulkan“ leitet sich …") is no answer; the phrase it governs is
NAMING_HEADS = frozenset({"wort", "begriff", "bezeichnung", "name", "ausdruck", "terminus"})
# An accusative object of these verbs is a predicate or a property, not a thing done: "Was hat der Vulkan?"
NO_OBJECT_VERBS = frozenset({"sein", "werden", "bleiben", "lauten", "heißen", "gelten", "haben", "geben"})
# Verbs whose object is an amount: "dauert ein Jahr", "beziffert sich auf sieben Milliarden" ask "Wie lange" or "Wie
# viel", never "Was" or "Worauf" (M30: "Was dauern Prüfungsvorbereitungskurse … ungefähr?"). The parse takes "misst"
# for a form of "missen"
AMOUNT_VERBS = frozenset({"dauern", "kosten", "betragen", "wiegen", "messen", "missen", "beziffern", "belaufen"})
# "zählen" counts only with an accusative ("zählt mehrere Tausend Mitglieder"); "zählt zu" names a membership and
# stays a question
COUNTING_VERBS = AMOUNT_VERBS | {"zählen"}
# "messen die Stromstärke" names a thing, "misst fast 50 Meter" an amount: behind these an object is one only with a
# number of its own (review of D60)
MEASURING_VERBS = frozenset({"messen", "missen"})
WO_PREPOSITIONS = {
    "an": "Woran", "am": "Woran", "auf": "Worauf", "aus": "Woraus", "bei": "Wobei", "beim": "Wobei",
    "durch": "Wodurch", "für": "Wofür", "gegen": "Wogegen", "in": "Worin", "im": "Worin", "mit": "Womit",
    "nach": "Wonach", "über": "Worüber", "um": "Worum", "unter": "Worunter", "von": "Wovon", "vom": "Wovon",
    "vor": "Wovor", "zu": "Wozu", "zum": "Wozu", "zur": "Wozu",
}  # fmt: skip
# Verbs whose phrase the parse calls a modifier although the verb governs it ("leitet sich von … ab")
GOVERNED = frozenset(
    {
        ("ableiten", "von"), ("abhängen", "von"), ("handeln", "von"), ("stammen", "von"), ("stammen", "aus"),
        ("beruhen", "auf"), ("basieren", "auf"), ("beziehen", "auf"), ("verweisen", "auf"), ("wirken", "auf"),
        ("bestehen", "aus"), ("entstehen", "aus"), ("hervorgehen", "aus"), ("gehören", "zu"), ("zählen", "zu"),
        ("führen", "zu"), ("beitragen", "zu"), ("beschäftigen", "mit"), ("befassen", "mit"), ("sorgen", "für"),
        ("warnen", "vor"), ("schützen", "vor"), ("berichten", "über"), ("verfügen", "über"),
    }
)  # fmt: skip
# Where the main clause ends: before ", weil …", ", was …" and the like, or at a semicolon or a dash
CLAUSE_ENDERS = frozenset(
    {"weil", "da", "obwohl", "wobei", "wodurch", "sodass", "nachdem", "während", "bevor", "indem", "wenn", "falls",
     "damit", "als", "was"}
)  # fmt: skip
CAUSES = frozenset({"weil", "da"})
CLAUSE_OPENERS = frozenset({"PRELS", "PRELAT", "PWS", "PWAV", "PWAT"})  # relative and interrogative pronouns
# Words that point ahead to what a colon introduces: "so rekonstruiert:", "folgende Gründe:"
CATAPHORA = frozenset({"so", "folgende", "folgenden", "folgender", "folgendes", "folgendermaßen", "nachstehend"})


def parse_ready(sentence: str) -> str:
    """The sentence as spaCy should see it: a year before the final full stop split off.

    de_core_news_md reads "im Jahr 1893." as an ordinal token "1893.", which leaves the year outside its phrase:
    measured on 2026-09-25, "Wann ergänzte Wilhelm Wien das Stefan-Boltzmann-Gesetz 1893?" came out of it.
    """
    return _YEAR_BEFORE_STOP.sub(r"\1 .", sentence)


def words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def unclear(text: str) -> bool:
    """Whether ``text`` leans on what an earlier sentence said: "diese Form", "aber", "den Begriff" of which word.

    "sowohl … als auch" is no such lean, "auch" alone is.
    """
    if _BARE_NAMING.search(text):
        return True
    return bool(words(re.sub(r"\bals auch\b", " ", text, flags=re.IGNORECASE)) & ANAPHORA)
