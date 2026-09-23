"""Rules for reading a topic and the beginning of an article (M8, docs/entwicklung/02-weltwissen.md).

Pure functions over strings: which words of a subject decide between meanings, which meaning of a disambiguation
page to take, which forms of a topic to try as titles, and what a candidate shows of itself. The registry applies
them to the archives (app/sources/zim/registry.py).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Sequence

from app.sources.zim.html import ParsedArticle

TITLE_WEIGHT = 3  # a context word in the title of a meaning outweighs one in its text
OPENING_CHARS = 160  # the beginning of a candidate's text an article chooser sees, as measured (M8)
# School words a context carries that say nothing about a meaning ("Fach Physik", "Klasse 7", "Sekundarstufe I");
# "fach" also sits in "mehrfach" and "Fachbereich" and decided meanings by chance (M8, 2026-09-23)
GENERIC_CONTEXT = frozenset(
    {
        "fach",
        "klasse",
        "klassen",
        "klassenstufe",
        "jahrgang",
        "jahrgangsstufe",
        "stufe",
        "sekundarstufe",
        "primarstufe",
        "grundschule",
        "unterstufe",
        "mittelstufe",
        "oberstufe",
        "schule",
        "gymnasium",
        "realschule",
        "hauptschule",
        "gesamtschule",
        "oberschule",
        "berufsschule",
        "hochschule",
        "universität",
        "studium",
        "kinder",
        "lernende",
        "schüler",
        "schülerinnen",
    }
)
QUERY_STOPWORDS = frozenset({"oder", "ohne", "über", "unter", "nach", "eine", "einer", "eines", "einem", "einen"})
INFLECTION_SUFFIXES = ("en", "es", "n", "s", "e")
LEADING_ARTICLE = re.compile(r"^(?:der|die|das)\s+(.+)$", re.IGNORECASE)
# The defining sentence of a film, a book or a record: "… ist ein zweiteiliger Spielfilm"
WORK = re.compile(
    r"\b(?:Spielfilm|Fernsehfilm|Kinofilm|Film|Fernsehserie|Roman|Erzählung|Album|Lied|Song|Single|Oper|"
    r"Theaterstück|Hörspiel|Computerspiel|Videospiel|Zeitschrift)\b"
)
BRACKETS = re.compile(r"\([^()]*\)")  # innermost first; nested brackets need a second pass
# A biography opens with the dates behind the name: "Peter Wende (* 17. März 1936 in Athen; …)"
PERSON = re.compile(r"\(\s*(?:\*|geb(?:oren|\.))")
# "Kreislauf des Wassers", "Ursachen der Französischen Revolution"
GENITIVE = re.compile(r"^(\w[\w-]*)\s+(?:des|der)\s+(.+)$")
# Words that ask for one aspect of a topic: the topic is what follows them
ASPECT_WORDS = frozenset(
    {
        "ursachen",
        "ursache",
        "aufbau",
        "folgen",
        "bedeutung",
        "entstehung",
        "entwicklung",
        "geschichte",
        "grundlagen",
        "merkmale",
        "arten",
        "formen",
        "bestandteile",
        "funktionsweise",
        "eigenschaften",
        "ablauf",
        "verlauf",
        "rolle",
        "einfluss",
        "wirkung",
        "auswirkungen",
        "einführung",
        "überblick",
    }
)
_WORD = re.compile(r"\w+")


def listed_meanings(article: ParsedArticle) -> list[str]:
    """The links a disambiguation page offers as meanings - the ones that stand in its list.

    Such a page opens with a sentence of its own, and the links in it are etymology, not meanings. They
    stand in front of everything else, so with no context to score against they won: measured against the
    real Wikipedia on 2026-09-21, the topic "Punkt" resolved to "Latein" and "Wende" to "Althochdeutsch",
    and both were reported as alternative meanings as well.

    Deciding this by searching the list *text* was measured and thrown out: it dropped 19 real meanings to
    remove 3 etymology links, because the rendered label of a link is not its title - "Punktierung (Musik)"
    reads as "Punktierung", "Bezirk Friedrichshain-Kreuzberg" as "Friedrichshain-Kreuzberg". Where a link
    stands is not a guess, so the parser records it.

    A page whose meanings are prose rather than a list keeps all its links: narrowing to nothing would lose
    the topic altogether.
    """
    return list(article.list_links) or list(article.links)


def context_score(stems: Collection[str], title: str, text: str) -> int:
    """How strongly a candidate of a disambiguation page speaks for the caller's context.

    A stem counts ``TITLE_WEIGHT`` times when it begins a word of the title and once when it begins a word of
    the opening text. The title matters most, because that is where a German disambiguation page keeps the
    distinction - "Rolle (Physik)", "Feld (Numismatik)" - while the body often never repeats it: the article
    behind "Rolle (Physik)" opens with "Eine Rolle ist ein Maschinenelement" and does not contain the word
    Physik at all. Stems match the beginning of a word, so "chemi" finds "Chemie" and "chemische" alike.
    """
    title_words = _WORD.findall(title.lower())
    text_words = _WORD.findall(text[:1500].lower())
    return sum(
        TITLE_WEIGHT * any(word.startswith(stem) for word in title_words)
        + any(word.startswith(stem) for word in text_words)
        for stem in stems
    )


def disambiguation_stems(terms: Iterable[str]) -> set[str]:
    """Stems of the words that may decide between meanings: four letters and more, school words left out.

    A stem that begins with another one adds nothing and is dropped: with "Mathematik" and "mathematisch" both in,
    a single "mathematischen" counted twice and made "Ableitung (Informatik)" a sure pick (M8, 2026-09-23).
    """
    words = {word for term in terms for word in _WORD.findall(term.lower()) if len(word) >= 4}
    stems = {word[:-1] if len(word) >= 6 else word for word in words - GENERIC_CONTEXT}
    return {stem for stem in stems if not any(stem != other and stem.startswith(other) for other in stems)}


def inflection_variants(topic: str) -> list[str]:
    """The topic with an inflection ending stripped from its last word: "Lineare Funktionen" -> "Lineare Funktion"."""
    head, _, last = topic.strip().rpartition(" ")
    variants = [
        f"{head} {last[: -len(suffix)]}".strip()
        for suffix in INFLECTION_SUFFIXES
        if last.lower().endswith(suffix) and len(last) - len(suffix) >= 4
    ]
    return [variant for variant in dict.fromkeys(variants) if variant != topic]


def without_brackets(text: str) -> str:
    """The text without its bracketed parts: spellings, dates and abbreviations after a name."""
    while (plain := BRACKETS.sub("", text)) != text:
        text = plain
    return text


def looks_like_work(text: str) -> bool:
    """Whether the defining first sentence of an article presents a film, a book, a record or a play.

    Brackets go first: "Der Fall (franz. La Chute) ist ein Roman" would otherwise end its sentence at "franz.".
    """
    return bool(WORK.search(without_brackets(text[:600]).split(". ")[0][:300]))


def opening(text: str) -> str:
    """The beginning of an article on one line, without brackets: what an article chooser sees of a candidate."""
    return " ".join(without_brackets(text[:800]).split())[:OPENING_CHARS]


def looks_like_person(text: str) -> bool:
    """Whether an article opens as a biography: the name, then its dates, "Peter Wende (* 17. März 1936 …"."""
    return bool(PERSON.search(text[:200]))


def pick_meaning(meanings: Sequence[tuple[str, str]], stems: Collection[str]) -> tuple[int, bool]:
    """Which of the (title, opening text) meanings of a disambiguation page to take, and whether that is sure.

    The highest context score wins, ties go to the first listed; the choice is confident when it alone scores
    highest. People and works listed below an ordinary meaning come after every ordinary one, whatever they
    score: they merely carry the word as a name, and "Geschichte: Wende" became the historian Peter Wende,
    "Deutsch: Fall" the writer Ludwig Ganghofer (M8, 2026-09-23). A person the page lists first is its main
    meaning ("Luther" -> Martin Luther) and keeps its place.
    """
    ranked: list[tuple[bool, int, int]] = []
    seen_ordinary = False
    for index, (title, text) in enumerate(meanings):
        side_topic = looks_like_person(text) or looks_like_work(text)
        ranked.append((side_topic and seen_ordinary, -context_score(stems, title, text), index))
        seen_ordinary = seen_ordinary or not side_topic
    ranked.sort()
    demoted, negative_score, index = ranked[0]
    unique = len(ranked) == 1 or ranked[1][:2] != (demoted, negative_score)
    return index, -negative_score > 0 and unique


def split_genitive(topic: str) -> tuple[str, str] | None:
    """ "Kreislauf des Wassers" -> ("Kreislauf", "Wassers"); ``None`` when the topic is no such phrase."""
    match = GENITIVE.match(topic.strip())
    return (match.group(1), match.group(2)) if match else None


def nominative(phrase: str) -> str:
    """A genitive phrase with its adjectives in the nominative: "Französischen Revolution" -> "Französische …"."""
    *adjectives, noun = phrase.split()
    return " ".join([*(word[:-1] if word.lower().endswith("en") else word for word in adjectives), noun])


def compound_candidates(head: str, rest: str) -> list[str]:
    """Compounds of a genitive phrase with one word after the article: "Kreislauf des Wassers" -> Wasserkreislauf."""
    if " " in rest.strip():
        return []
    stems = [rest, *(rest[: -len(suffix)] for suffix in INFLECTION_SUFFIXES if rest.lower().endswith(suffix))]
    return list(dict.fromkeys(f"{stem}{head.lower()}" for stem in stems if len(stem) >= 3))


def rank_by_query(query: str, titles: Sequence[str]) -> str | None:
    """The title that carries most words of the query, and the fewest others; ``None`` when none carries any.

    Title suggestions and full-text hits come in the archive's order, which put "Meereswärmekraftwerk" before
    "Wasserkreislauf" for "Kreislauf des Wassers" (M8, 2026-09-23). A query word counts when its stem stands
    anywhere in the title, so compounds match; ties keep the order of ``titles``.
    """
    stems = [
        word[: max(4, len(word) - 2)] if len(word) >= 6 else (word[:-1] if len(word) == 5 else word)
        for word in _WORD.findall(query.lower())
        if len(word) >= 4 and word not in QUERY_STOPWORDS
    ]
    best, best_score = None, 0.0
    for title in titles:
        lowered = title.lower()
        matched = [stem for stem in stems if stem in lowered]
        if not matched:
            continue
        letters = len(re.sub(r"\W", "", lowered)) or 1
        score = len(matched) + sum(len(stem) for stem in matched) / letters
        if score > best_score:
            best, best_score = title, score
    return best
