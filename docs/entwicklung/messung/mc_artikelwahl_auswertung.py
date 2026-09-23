"""Evaluation of the article selection (M8): main article, relevance of the corpus articles, old against new.

Reads the result of mc_artikelwahl.py, the blind labels (eval/artikelwahl/korpus_labels.yaml) and the LLM judge
(mc_artikel_richter.py). Relevance is reported twice, with the gold labels and with the judge's notes; agreement
between both is given as exact share and Cohen's kappa. Rounding half up, German number format.

Usage: python mc_artikelwahl_auswertung.py <ergebnis.json> <richter.json> <out.txt>
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

LABELS = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\artikelwahl\korpus_labels.yaml")
KINDS = {
    "normal": "normale Themen", "zusatz": "mit Klassen-, Stufen- oder Fachzusatz",
    "mehrdeutig_mit_fach": "mehrdeutig, Fach als Kontext", "mehrdeutig_ohne_kontext": "mehrdeutig, ohne Kontext",
    "variante": "Schreibvariante, Abkürzung, Mehrzahl", "ohne_eigenen_artikel": "ohne gleichnamigen Artikel zum Thema",
}
ORIGINS = {"primary": "Hauptartikel", "same_topic": "dasselbe Thema aus Klexikon", "linked": "verlinkter Unterartikel",
           "search": "Volltexttreffer je Baustein"}

result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
judge_raw = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
out_path = Path(sys.argv[3])
gold = yaml.safe_load(LABELS.read_text(encoding="utf-8"))["labels"]
judge = {t["topic"]: t["notes"] for t in judge_raw["topics"]}
lines: list[str] = []


def de(value: float, places: str = "1") -> str:
    rounded = Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{rounded:,}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(part: int, whole: int) -> str:
    return f"{de(100 * part / whole)} %" if whole else "–"


def shares(notes: list[int]) -> str:
    counts = Counter(notes)
    return " | ".join(pct(counts[n], len(notes)) for n in (2, 1, 0))


# 1 main article
lines += ["## Hauptartikel", "", "| Art der Anfrage | richtig |", "|---|---|"]
total = correct = 0
for kind, title in KINDS.items():
    flags = [a["richtig"] for a in result["anfragen"] if a["art"] == kind]
    total, correct = total + len(flags), correct + sum(flags)
    lines.append(f"| {title} | {sum(flags)} von {len(flags)} |")
lines.append(f"| **alle** | **{correct} von {total}** |")
lines += ["", "Falsch aufgelöst:", ""]
lines += [f"- {a['anfrage']} -> {a['titel']} (erwartet: {', '.join(a['akzeptiert'])})"
          for a in result["anfragen"] if not a["richtig"]]

# 2 corpus of the new service, 20 normal topics
rows = []
for topic, corpus in result["korpus"].items():
    for article in corpus["artikel"]:
        key = f"{article['projekt']}:{article['titel']}"
        rows.append({**article, "thema": topic, "gold": gold[topic][key], "richter": judge[topic].get(key)})
lines += ["", "## Korpus des neuen Dienstes (20 normale Themen)", "",
          "Anteile gehört zum Thema | verwandt | passt nicht", "",
          "| Artikel | Anzahl | Gold | Richter |", "|---|---|---|---|"]
for origin, title in ORIGINS.items():
    part = [r for r in rows if r["herkunft"] == origin]
    lines.append(f"| {title} | {len(part)} | {shares([r['gold'] for r in part])} | "
                 f"{shares([r['richter'] for r in part if r['richter'] is not None])} |")
lines.append(f"| **alle gewählten** | **{len(rows)}** | {shares([r['gold'] for r in rows])} | "
             f"{shares([r['richter'] for r in rows if r['richter'] is not None])} |")
kept = [r for r in rows if r["im_korpus"]]
dropped = [r for r in rows if not r["im_korpus"]]
lines.append(f"| davon mit Absätzen im Korpus | {len(kept)} | {shares([r['gold'] for r in kept])} | "
             f"{shares([r['richter'] for r in kept if r['richter'] is not None])} |")
lines.append(f"| davon ohne Absatz (Themenfilter) | {len(dropped)} | {shares([r['gold'] for r in dropped])} | "
             f"{shares([r['richter'] for r in dropped if r['richter'] is not None])} |")

paragraphs = sum(r["absaetze"] for r in rows)
printed = sum(r["gedruckt"] for r in rows)
lines += ["", "| Absätze | im Korpus | davon aus Artikeln „passt nicht“ (Gold) | gedruckt (Standard) | davon aus Artikeln „passt nicht“ (Gold) |",
          "|---|---|---|---|---|",
          f"| 20 Themen | {paragraphs} | {sum(r['absaetze'] for r in rows if r['gold'] == 0)} "
          f"({pct(sum(r['absaetze'] for r in rows if r['gold'] == 0), paragraphs)}) | {printed} | "
          f"{sum(r['gedruckt'] for r in rows if r['gold'] == 0)} ({pct(sum(r['gedruckt'] for r in rows if r['gold'] == 0), printed)}) |"]
lines += ["", "Artikel mit Absätzen im Korpus, die nach Gold nicht passen:", ""]
lines += [f"- {r['thema']}: {r['titel']} ({ORIGINS[r['herkunft']]}, {r['absaetze']} Absätze, {r['gedruckt']} gedruckt)"
          for r in kept if r["gold"] == 0]

# 3 old against new on the ten gold topics
lines += ["", "## Alter und neuer Dienst auf den zehn Goldthemen", "",
          "| Dienst | Artikel | je Thema (Median) | Gold: gehört | verwandt | passt nicht | Richter: gehört | verwandt | passt nicht |",
          "|---|---|---|---|---|---|---|---|---|"]
for label, per_topic in (
    ("alter Dienst (bester Fall)", {t: [f"wikipedia:{a['titel']}" for a in arts] for t, arts in result["alter_dienst"].items()}),
    ("neuer Dienst, Artikel mit Absätzen", {t: [f"{a['projekt']}:{a['titel']}" for a in c["artikel"] if a["im_korpus"]]
                                           for t, c in result["korpus"].items() if t in result["alter_dienst"]}),
):
    keys = [(t, k) for t, ks in per_topic.items() for k in ks]
    g = [gold[t][k] for t, k in keys]
    j = [judge[t][k] for t, k in keys if k in judge[t]]
    median = statistics.median(len(ks) for ks in per_topic.values())
    lines.append(f"| {label} | {len(keys)} | {de(median)} | {shares(g)} | {shares(j)} |")

# 4 agreement gold / judge
pairs = [(gold[t][k], n) for t, notes in judge.items() for k, n in notes.items()]
agree = sum(a == b for a, b in pairs)
n = len(pairs)
p_o = agree / n
gold_counts, judge_counts = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
p_e = sum(gold_counts[c] * judge_counts[c] for c in (0, 1, 2)) / (n * n)
kappa = (p_o - p_e) / (1 - p_e)
confusion = Counter(pairs)
lines += ["", "## Übereinstimmung Gold und Richter", "",
          f"{agree} von {n} Artikeln gleich bewertet ({pct(agree, n)}), Cohens Kappa {de(kappa, '0.01')}.", "",
          "| Gold \\ Richter | 2 | 1 | 0 |", "|---|---|---|---|"]
lines += [f"| {g} | {confusion[(g, 2)]} | {confusion[(g, 1)]} | {confusion[(g, 0)]} |" for g in (2, 1, 0)]
lines += ["", f"Richter: {judge_raw['spent']['calls']} Aufrufe, {judge_raw['spent']['tokens']} Tokens, "
          f"{judge_raw['spent']['failed']} fehlgeschlagen."]

text = "\n".join(lines) + "\n"
out_path.write_text(text, encoding="utf-8")
print(text)
