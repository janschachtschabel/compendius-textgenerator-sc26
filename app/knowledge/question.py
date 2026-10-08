"""The keywords of a question for the rules (M73): what a question or a sentence names, in its order.

Without an LLM a question went whole into the full-text search, and llm-free found a foreign article for about half of
the questions of a teacher: "Mond" for "Wie entsteht ein Regenbogen …?", "Antikörper" for the digestion (M70). Its
keywords, tried in the order the question names them, each resolved as a topic is, find the article where the rules
only guessed: of 60 questions two blind judges found 43 to 45 articles fitting instead of 22 to 24, and 2 instead of
24 to 25 foreign; five of the 60 were better before (M73).

The rules take them where the input reads as a text - a sentence, a question, more than six words (D72) - and
only guessed its article: on short topics they changed 41 of 195 topics of M63, as often for the worse ("Plastik im
Meer" -> "Meer" instead of "Plastikmüll in den Ozeanen") as for the better.

A keyword at a word of the question, the longest first: a pair with "und" ("Ebbe und Flut"), an adjective with its
noun in the forms a title has ("nachhaltiger Landwirtschaft" -> "Nachhaltige Landwirtschaft"), a run of capitalised
words with its declined adjectives in their basic forms too ("Ersten Weltkriegs" -> "Erster Weltkrieg"), the noun
alone and without its genitive or plural ending. Question words, articles and the words that name the kind of
question ("Unterschied", "Ursachen", "Rolle") or a class of things ("Tiere", "Aufgaben") are none.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.models import Resolution
from app.knowledge.resolution import resolve_topic
from app.sources.zim.registry import ZimRegistry

# The methods that reach the article a keyword names; a suggestion or a full-text hit is a guess (M25)
EXACT = frozenset({"title", "variant"})
_FUNCTION = frozenset(
    "wie was warum wieso weshalb weswegen welche welcher welches welchen welchem wer wen wem wessen wo woher wohin "
    "wann womit wozu wodurch erkläre erklärt beschreibe nenne zeige die der das den dem des ein eine einen einem eines "
    "und oder für mit bei beim im in am an auf aus von vom zum zur zu über unter nach vor gegen ohne um es man sich "
    "sie er wir ihr unser unsere unserer einfach dagegen kann können ist sind war waren hat haben zwischen neben "
    "hinter wegen oben unten innen außen eben gerne heute lange immer jede jeder jedes jeden jedem diese dieser "
    "dieses diesen diesem alle allen aller viele vielen einige einigen andere anderen ich mich mir mein meine "
    "meiner meinem meinen du dich dir dein deine deiner".split()
)
_GENERIC = frozenset(
    "unterschied unterschiede ursache ursachen rolle beispiel beispiele folge folgen gefahren gefahr chancen chance "
    "entstehung bedeutung klasse klassen schüler schülerinnen unterricht thema frage teil art arten grundlagen "
    "überblick einführung funktion funktionsweise aufbau entwicklung vergleich zusammenhang möglichkeiten vorteile "
    "nachteile grundschule sekundarstufe jugendliche kinder aufgabe aufgaben tiere pflanzen menschen lebewesen länder "
    "stoffe dinge leute personen regeln gründe grund probleme problem eigenschaften merkmale formen methoden "
    "erfindung".split()
)
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzäöüß-")
_DECLINED = ("en", "em", "er", "es", "e")
MIN_STEM = 4  # a noun stripped of its ending keeps at least this many letters ("Krieg", not "Kri")


def keywords(text: str) -> list[str]:
    """The keywords of ``text`` in the order it names them; at each word the longest first (module docstring)."""
    words = _words(text)
    found: list[str] = []
    for i, word in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        after = words[i + 2] if i + 2 < len(words) else ""
        if _content(word) and nxt == "und" and _content(after):
            found.append(f"{word} und {after}")
        if word[:1].islower() and word not in _FUNCTION and len(word) > MIN_STEM and _content(nxt):
            if word.endswith(_DECLINED):
                found += [f"{a} {n}" for a in _adjective_forms(word) for n in _noun_forms(nxt)]
        if _content(word):
            found += _run_forms(words[i:])
            found += _noun_forms(word)
    return list(dict.fromkeys(found))


def resolve_by_keywords(
    registry: ZimRegistry,
    text: str,
    *,
    context: Sequence[str] = (),
    query: str | None = None,
    terms: Sequence[str] = (),
) -> Resolution | None:
    """The article of the first keyword of ``text`` that names one exactly (``EXACT``), else ``None``; the resolution
    keeps ``query``, what was asked."""
    for word in keywords(text):
        resolution = resolve_topic(registry, word, context=context, query=query, terms=terms)
        if resolution.resolved and resolution.method in EXACT:
            return resolution
    return None


def _words(text: str) -> list[str]:
    out, word = [], ""
    for char in text:
        if char.lower() in _LETTERS:
            word += char
            continue
        if word:
            out.append(word)
        word = ""
    return [*out, word] if word else out


def _content(word: str) -> bool:
    lower = word.lower()
    return word[:1].isupper() and lower not in _FUNCTION and lower not in _GENERIC


def _run_forms(words: Sequence[str]) -> list[str]:
    """A run of capitalised words from the first of ``words`` ("Joseph von Eichendorff"), the longest first and down
    to two words ("Weimarer Republik Krisenjahre", "Weimarer Republik"), its last noun in its forms and, for two words,
    its first in the basic forms of an adjective ("Dreißigjährige Krieg" -> "Dreißigjähriger Krieg")."""
    run = [words[0]]
    for later in words[1:]:
        if not (_content(later) or later == "von"):
            break
        run.append(later)
    forms: list[str] = []
    for length in range(len(run), 1, -1):
        part = run[:length]
        if part[-1] == "von":
            continue
        last = _noun_forms(part[-1])
        forms += [" ".join([*part[:-1], form]) for form in last]
        if length == 2 and part[0].lower().endswith(_DECLINED):
            forms += [f"{head} {form}" for head in _adjective_forms(part[0]) for form in last]
    return forms


def _noun_forms(noun: str) -> list[str]:
    """The noun, and without a genitive or plural ending: Weltkriegs -> Weltkrieg, Netzwerke -> Netzwerk."""
    forms = [noun]
    for ending in ("es", "s", "e", "en", "n"):
        if noun.endswith(ending) and len(noun) - len(ending) >= MIN_STEM:
            forms.append(noun[: -len(ending)])
    return list(dict.fromkeys(forms))


def _adjective_forms(adjective: str) -> list[str]:
    """A declined adjective in the forms a title has: nachhaltiger -> Nachhaltige, Nachhaltiger, Nachhaltiges."""
    stem = adjective
    for ending in _DECLINED:
        if adjective.lower().endswith(ending) and len(adjective) - len(ending) >= 3:
            stem = adjective[: -len(ending)]
            break
    head = stem[:1].upper() + stem[1:]
    return [head + "e", head + "er", head + "es"]
