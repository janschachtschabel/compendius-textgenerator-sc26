"""M37 evaluated: how well each way builds part 1 of a set-like or mixed topic, from the blind article grades.

Per way: the grade of the main article, the paragraphs printed from articles graded 2, 1 and 0, the compendia of
which at least half the printed paragraphs come from articles graded 2 ("brauchbar", as M23), the filled blocks, the
persons of the actor block, tokens and seconds. The topics fall into three kinds, set by hand before the run: those
with an article of their own, groups without one, and topics that join two subjects.

With --normal the run is the control on the 20 ordinary topics of M1, shown as one kind.

Usage (from the project folder): python mc_sammelthemen_auswertung.py <m37 run.json> <grades.yaml> [<second.yaml>]
[--normal]
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

WAYS = {
    "R": "llm-free heute",
    "B": "balanced heute",
    "A": "Entitäten der alten App",
    "N": "LLM nennt Übersicht + Teile",
}
OWN_ARTICLE = {
    "Edelgase", "Weltreligionen", "erneuerbare Energien", "Frauen in der Wissenschaft", "Musik der Romantik",
    "griechische Götter", "deutsche Bundeskanzler",
}  # fmt: skip
JOINED = {"Klimawandel und Landwirtschaft", "Mathematik in der Musik", "Chemie im Alltag", "Frauen im Mittelalter"}


def kind_of(topic: str) -> str:
    if topic in OWN_ARTICLE:
        return "eigener Artikel"
    return "Verbindung" if topic in JOINED else "Gruppe"


def grades_of(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {(entry["thema"], entry["artikel"]): entry for entry in data["noten"]}


def table(rows: list[dict[str, Any]], grades: dict[tuple[str, str], dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for way in WAYS:
        cell: dict[str, Any] = {"haupt": [0, 0, 0], "absaetze": [0, 0, 0], "brauchbar": 0, "themen": 0,
                                "bausteine": [], "personen": [], "tokens": [], "sekunden": []}  # fmt: skip
        for row in rows:
            result = row["wege"][way]
            if "hauptartikel" not in result:
                continue
            topic = row["thema"]
            cell["themen"] += 1
            main = grades.get((topic, result["hauptartikel"]))
            if main is not None:
                cell["haupt"][2 - main["note"]] += 1
            printed = [0, 0, 0]
            for entry in result["gedruckt"]:
                printed[2 - grades[(topic, entry["titel"])]["note"]] += entry["absaetze"]
            cell["absaetze"] = [a + b for a, b in zip(cell["absaetze"], printed, strict=True)]
            cell["brauchbar"] += sum(printed) > 0 and printed[0] * 2 >= sum(printed)
            cell["bausteine"].append(result["bausteine"])
            cell["personen"].append(len(result["personen"]))
            cell["tokens"].append(result.get("tokens_dienst", 0) + result.get("tokens_frage", 0))
            cell["sekunden"].append(result["sekunden"] + result.get("sekunden_frage", 0))
        out[way] = cell
    return out


def show(rows: list[dict[str, Any]], grades: dict[tuple[str, str], dict[str, Any]], title: str) -> None:
    print(f"\n{title} ({len(rows)} Themen)")
    print(f"{'Weg':32s} {'Haupt 2/1/0':>12s} {'Absätze 2/1/0':>16s} {'passend':>8s} {'brauchbar':>10s} "
          f"{'Bausteine':>9s} {'Personen':>8s} {'Tokens':>7s} {'s':>5s}")  # fmt: skip
    for way, cell in table(rows, grades).items():
        total = sum(cell["absaetze"]) or 1
        print(
            f"{way} {WAYS[way]:30s} {'/'.join(map(str, cell['haupt'])):>12s} "
            f"{'/'.join(map(str, cell['absaetze'])):>16s} {cell['absaetze'][0] / total * 100:7.0f}% "
            f"{cell['brauchbar']:5d}/{cell['themen']:<4d} {statistics.mean(cell['bausteine'] or [0]):9.1f} "
            f"{statistics.median(cell['personen'] or [0]):8.0f} {statistics.median(cell['tokens'] or [0]):7.0f} "
            f"{statistics.median(cell['sekunden'] or [0]):5.1f}"
        )


NORMAL = "--normal" in sys.argv
args = [arg for arg in sys.argv[1:] if arg != "--normal"]
run = json.loads(Path(args[0]).read_text(encoding="utf-8"))
rows = run["themen"]
first = grades_of(Path(args[1]))
second = grades_of(Path(args[2])) if len(args) > 2 else None
if second is not None:
    agreement(first, second)
for name, grades in [("erste Noten", first)] + ([("zweite Noten", second)] if second is not None else []):
    print(f"\n=== {name} ===")
    show(rows, grades, "gewöhnliche Themen (M1)" if NORMAL else "alle")
    for kind in () if NORMAL else ("eigener Artikel", "Gruppe", "Verbindung"):
        show([row for row in rows if kind_of(row["thema"]) == kind], grades, kind)
