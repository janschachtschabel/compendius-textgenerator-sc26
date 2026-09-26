"""M36 evaluated: precision, recall and F1 of every way of /api/v2/entities against the pooled grades.

A way's article counts as right when its grade is 2 (an entity or subject term of the text, the article meaning
exactly that); recall counts against all articles graded 2 that any way linked for that text (pooling, as M23). The
check keeps what the LLM graded 2, or with ">=1" also what it graded 1. The run of 2026-09-26 left one article of the
combined rules out of its pool (the letter M, from an English text): it has no grade and counts as 0.

Usage (from the project folder): python mc_entitaeten_auswertung.py <m36 run.json> <grades.yaml> [<second grades.yaml>]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

import yaml
from noten import agreement

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def grades_of(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {(entry["node_id"], entry["artikel"]): entry for entry in data["noten"]}


def ways_of(row: dict[str, Any]) -> dict[str, list[str]]:
    """Every way's articles for one text, the checked ones from the LLM's notes."""
    ways, notes = row["wege"], row["wege"]["pruefung"]["noten"]
    rules, union = ways["regeln"]["artikel"], row["pool"]
    return {
        "ner": ways["ner"]["artikel"],
        "dictionary": ways["dictionary"]["artikel"],
        "ner + dictionary (heute)": rules,
        "LLM nennt (extract)": ways["extract"]["artikel"],
        "heute + LLM prüft (2)": [t for t in rules if notes.get(t) == 2],
        "heute + LLM prüft (>=1)": [t for t in rules if notes.get(t, 0) >= 1],
        "alle zusammen": union,
        "alle + LLM prüft (2)": [t for t in union if notes.get(t) == 2],
        "alle + LLM prüft (>=1)": [t for t in union if notes.get(t, 0) >= 1],
        "LLM nennt + prüft (2)": [t for t in ways["extract"]["artikel"] if notes.get(t) == 2],
    }


def note(grades: dict[tuple[str, str], dict[str, Any]], node_id: str, title: str) -> int:
    """The grade of an article, 0 for one outside the graded pool."""
    entry = grades.get((node_id, title))
    return int(entry["note"]) if entry is not None else 0


def scores(rows: list[dict[str, Any]], grades: dict[tuple[str, str], dict[str, Any]]) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {}
    for row in rows:
        right = {t for t in row["pool"] if note(grades, row["node_id"], t) == 2}
        for way, found in ways_of(row).items():
            cell = table.setdefault(way, {"gefunden": 0, "richtig": 0, "passend_gesamt": 0, "note0": 0})
            cell["gefunden"] += len(found)
            cell["richtig"] += sum(1 for t in found if t in right)
            cell["note0"] += sum(1 for t in found if note(grades, row["node_id"], t) == 0)
            cell["passend_gesamt"] += len(right)
    for cell in table.values():
        p = cell["richtig"] / cell["gefunden"] if cell["gefunden"] else 0.0
        r = cell["richtig"] / cell["passend_gesamt"] if cell["passend_gesamt"] else 0.0
        cell.update(p=p, r=r, f1=2 * p * r / (p + r) if p + r else 0.0)
    return table


run = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rows = [row for row in run["materialien"] if "wege" in row]
first = grades_of(Path(sys.argv[2]))
second = grades_of(Path(sys.argv[3])) if len(sys.argv) > 3 else None
if second is not None:
    agreement(first, second)

ungraded = [(r["node_id"], t) for r in rows for t in r["wege"]["regeln"]["artikel"] if (r["node_id"], t) not in first]
print(f"\n{len(rows)} Materialtexte, {sum(len(r['pool']) for r in rows)} verknüpfte Artikel im Pool")
print(f"ohne Note, als 0 gezählt: {ungraded}")
tables = [scores(rows, first)] + ([scores(rows, second)] if second is not None else [])
print(f"\n{'Weg':28s} {'Artikel':>8s} {'P':>11s} {'R':>11s} {'F1':>11s} {'Note 0':>8s}")
for way in tables[0]:
    cells = [table[way] for table in tables]

    def both(key: str, cells: list[dict[str, float]] = cells) -> str:
        values = [f"{cell[key]:.2f}" for cell in cells]
        return values[0] + (f" ({values[1]})" if len(values) > 1 else "")

    zero = int(cells[0]["note0"])
    print(f"{way:28s} {int(cells[0]['gefunden']):8d} {both('p'):>11s} {both('r'):>11s} {both('f1'):>11s} {zero:8d}")

extract_tokens = [r["wege"]["extract"]["tokens"] for r in rows]
check_tokens = [r["wege"]["pruefung"]["tokens"] for r in rows]
print(
    f"\nTokens je Text im Median: LLM nennt {statistics.median(extract_tokens):.0f}, "
    f"LLM prüft {statistics.median(check_tokens):.0f}; Sekunden im Median: "
    f"LLM nennt {statistics.median(r['wege']['extract']['sekunden'] for r in rows):.1f}, "
    f"LLM prüft {statistics.median(r['wege']['pruefung']['sekunden'] for r in rows):.1f}, "
    f"Regeln (Endpunkt, mit HTTP) {statistics.median(r['wege']['regeln']['sekunden'] for r in rows):.2f}"
)
