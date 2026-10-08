"""Messskript M73 (08.10.2026): ob die Regeln eine Frage über ihre Stichwörter besser auflösen.

M70: llm-free fand für etwa die Hälfte von 20 Fragen einer Lehrkraft einen sachfremden Artikel („Mond“ für den
Regenbogen), denn die Regeln suchen mit der ganzen Frage im Volltext. Der Vorschlag (Entscheidungsgrundlage des Audits
vom 03.10., Zeile 5): die Frage auf ihre Stichwörter kürzen. Dieses Skript vergleicht je Eingabe

- ``heute``: den Hauptartikel von ``llm-free`` wie der Dienst ihn findet;
- ``stichwort``: die Stichwörter der Frage, je eines aufgelöst, wie die Regeln ein Thema auflösen; das erste, das
  einen Artikel genau trifft (Titel, Schreibvariante, sichere Begriffsklärung), gilt. Stichwörter sind, in dieser
  Reihenfolge: Paare mit „und“ („Ebbe und Flut“), Adjektiv und Nomen in der Grundform („Erster Weltkrieg“,
  „Nachhaltige Landwirtschaft“), Folgen großgeschriebener Wörter („Weimarer Republik“), dann einzelne Nomen - ohne
  Fragewörter, allgemeine Wörter („Unterschied“, „Ursachen“, „Tiere“) und Zusätze für die Klasse.

Einmal-Container mit den Archiven, ohne LLM:

  cat mc_fragen_regeln.py | docker compose run --rm --no-deps -T -v <ordner>:/x:ro api python - /x/fragen.json

Ergebnis als JSON nach der Zeile JSON-START.
"""

import json
import sys

from app.domain.requests import GenerateRequest
from app.knowledge.resolution import resolve_topic
from app.knowledge.topic import normalize_topic
from app.wiring import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

FUNCTION = {
    "wie", "was", "warum", "wieso", "weshalb", "weswegen", "welche", "welcher", "welches", "welchen", "welchem",
    "wer", "wen", "wem", "wessen", "wo", "woher", "wohin", "wann", "womit", "wozu", "wodurch", "erkläre", "erklärt",
    "beschreibe", "nenne", "zeige", "die", "der", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "eines",
    "und", "oder", "für", "mit", "bei", "beim", "im", "in", "am", "an", "auf", "aus", "von", "vom", "zum", "zur", "zu",
    "über", "unter", "nach", "vor", "gegen", "ohne", "um", "es", "man", "sich", "sie", "er", "wir", "ihr", "unser",
    "unsere", "unserer", "einfach", "dagegen", "kann", "können", "ist", "sind", "war", "waren", "hat", "haben",
}
GENERIC = {
    "unterschied", "unterschiede", "ursache", "ursachen", "rolle", "beispiel", "beispiele", "folge", "folgen",
    "gefahren", "gefahr", "chancen", "chance", "entstehung", "bedeutung", "klasse", "klassen", "schüler",
    "schülerinnen", "unterricht", "thema", "frage", "teil", "art", "arten", "grundlagen", "überblick", "einführung",
    "funktion", "funktionsweise", "aufbau", "entwicklung", "vergleich", "zusammenhang", "möglichkeiten", "vorteile",
    "nachteile", "grundschule", "sekundarstufe", "jugendliche", "kinder", "aufgabe", "aufgaben", "tiere", "pflanzen",
    "menschen", "lebewesen", "länder", "stoffe", "dinge", "leute", "personen", "regeln", "gründe", "grund",
    "probleme", "problem", "eigenschaften", "merkmale", "formen", "methoden", "erfindung",
}
ACCEPTED = {"title", "variant"}
LETTERS = set("abcdefghijklmnopqrstuvwxyzäöüß-")


def words_of(text):
    out, word = [], ""
    for char in text:
        if char.lower() in LETTERS:
            word += char
        elif word:
            out.append(word)
            word = ""
    return [*out, word] if word else out


def content(word):
    return word[:1].isupper() and word.lower() not in FUNCTION and word.lower() not in GENERIC


def noun_forms(noun):
    """The noun, without a genitive or plural ending as well: Weltkriegs -> Weltkrieg, Netzwerke -> Netzwerk."""
    forms = [noun]
    for ending in ("es", "s", "e", "en", "n"):
        if noun.endswith(ending) and len(noun) - len(ending) >= 4:
            forms.append(noun[: -len(ending)])
    return list(dict.fromkeys(forms))


def adjective_forms(adjective):
    """A declined adjective in the forms a title has: nachhaltiger -> Nachhaltige, Nachhaltiger, Nachhaltiges."""
    stem = adjective
    for ending in ("en", "em", "er", "es", "e"):
        if adjective.lower().endswith(ending) and len(adjective) - len(ending) >= 3:
            stem = adjective[: -len(ending)]
            break
    head = stem[:1].upper() + stem[1:]
    return [head + "e", head + "er", head + "es"]


def keywords(text):
    """The keywords in the order the text names them; at each word the longest first: a pair with „und“, an adjective
    with its noun, a run of capitalised words (its declined adjectives in their basic forms too), the noun alone."""
    words = words_of(text)
    found = []
    for i, word in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        after = words[i + 2] if i + 2 < len(words) else ""
        here = []
        if content(word) and nxt == "und" and content(after):
            here.append(f"{word} und {after}")
        if word[:1].islower() and word.lower() not in FUNCTION and len(word) > 4 and content(nxt) and (
            word.lower().endswith(("en", "em", "er", "es", "e"))
        ):
            here += [f"{a} {n}" for a in adjective_forms(word) for n in noun_forms(nxt)]
        if content(word):
            run = [word]
            for later in words[i + 1 :]:
                if content(later) or (later == "von" and run):
                    run.append(later)
                else:
                    break
            while run and run[-1] == "von":
                run.pop()
            if len(run) > 1:
                last = noun_forms(run[-1])
                here += [" ".join([*run[:-1], form]) for form in last]
                heads = [adjective_forms(w) if w.lower().endswith(("en", "em", "er", "es", "e")) else [w] for w in run[:-1]]
                if len(heads) == 1:
                    here += [f"{a} {form}" for a in heads[0] for form in last]
            here += noun_forms(word)
        found += here
    return list(dict.fromkeys(found))


inputs = json.loads(open(sys.argv[1], encoding="utf-8").read())
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
registry = service.registry.view()
rows = []
for text in inputs:
    try:
        today = service.prepare(GenerateRequest(topic=text, parts=["world"], preset="llm-free")).resolution
        heute = {"title": today.title, "method": today.method}
    except Exception as exc:  # a measurement records the failure and goes on
        heute = {"error": f"{type(exc).__name__}"}
    normalized = normalize_topic(text).topic
    tried, chosen = [], None
    for word in keywords(normalized):
        resolution = resolve_topic(registry, word)
        tried.append({"word": word, "title": resolution.title, "method": resolution.method})
        if resolution.resolved and resolution.method in ACCEPTED:
            chosen = {"word": word, "title": resolution.title, "method": resolution.method}
            break
    rows.append({"input": text, "heute": heute, "stichwort": chosen, "versucht": tried[:12]})
    print(f"# {text[:50]}: {heute.get('title')} / {chosen and chosen['title']}", file=sys.stderr, flush=True)

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
