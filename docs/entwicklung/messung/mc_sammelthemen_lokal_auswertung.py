"""M40 evaluated: the question N to small local models, next to llm-free as it is and N with gpt-6-luna.

Per way the grade of the main article, the paragraphs printed from articles graded 2, 1 and 0 and the compendia of
which at least half the printed paragraphs come from articles graded 2 ("brauchbar", as M23, M37 and M38). R is
llm-free as it is (the run of M38, which printed what M37 printed), N the question to gpt-6-luna (M37). The local models
are candidates for llm-free: where one names no article the archive has, the service would stay with llm-free as it
is, and that fallback counts, so a model is not measured on its good topics only. R2 is llm-free with the main article
and its twin only (mc_sammelthemen_nur_haupt.py): what a smaller corpus alone does, without any model. The paragraphs
printed and the blocks filled show what a smaller corpus costs.

Usage (from the project folder):
python mc_sammelthemen_lokal_auswertung.py <m40.json> <m38.json> <m37.json> <r2.json> <grades.yaml> [<second.yaml>]
[--normal]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

WAYS = {
    "R": "llm-free heute",
    "R2": "llm-free, nur Haupt und Zwilling",
    "N": "N mit gpt-6-luna (M37)",
    "LF7": "N mit LFM2-700M, lokal",
    "LF12": "N mit LFM2.5-1.2B, lokal",
    "Q06": "N mit Qwen3-0.6B, lokal",
}
LOCAL = ("LF7", "LF12", "Q06")
OWN_ARTICLE = {
    "Edelgase", "Weltreligionen", "erneuerbare Energien", "Frauen in der Wissenschaft", "Musik der Romantik",
    "griechische Götter", "deutsche Bundeskanzler",
}  # fmt: skip
JOINED = {"Klimawandel und Landwirtschaft", "Mathematik in der Musik", "Chemie im Alltag", "Frauen im Mittelalter"}


def kind_of(topic: str) -> str:
    if topic in OWN_ARTICLE:
        return "eigener Artikel"
    return "Verbindung" if topic in JOINED else "Gruppe"


def grades_of(path: Path) -> dict[tuple[str, str], int]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {(entry["thema"], entry["artikel"]): int(entry["note"]) for entry in data["noten"]}


def ways_of(
    m40: dict[str, Any], m38: dict[str, Any], m37: dict[str, Any], r2: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    ways = {"R": m38["wege"]["R"], "R2": r2["wege"]["R2"], "N": m37["wege"]["N"]}
    for way in LOCAL:
        result = m40["wege"][way]
        ways[way] = result if "hauptartikel" in result else {**m38["wege"]["R"], "rueckfall": True}
    return ways


def table(rows: list[tuple[str, dict[str, dict[str, Any]]]], grades: dict[tuple[str, str], int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for way in WAYS:
        cell: dict[str, Any] = {"haupt": [0, 0, 0], "absaetze": [0, 0, 0], "brauchbar": 0, "themen": 0,
                                "rueckfall": 0, "bausteine": [], "ohne_note": []}  # fmt: skip
        for topic, ways in rows:
            result = ways[way]
            cell["themen"] += 1
            cell["rueckfall"] += bool(result.get("rueckfall"))
            main = grades.get((topic, result["hauptartikel"]))
            if main is not None:
                cell["haupt"][2 - main] += 1
            printed = [0, 0, 0]
            for entry in result["gedruckt"]:
                note = grades.get((topic, entry["titel"]))
                if note is None:
                    cell["ohne_note"].append((topic, entry["titel"]))
                    note = 0
                printed[2 - note] += entry["absaetze"]
            cell["absaetze"] = [a + b for a, b in zip(cell["absaetze"], printed, strict=True)]
            cell["brauchbar"] += sum(printed) > 0 and printed[0] * 2 >= sum(printed)
            cell["bausteine"].append(result["bausteine"])
        out[way] = cell
    return out


def show(rows: list[tuple[str, dict[str, dict[str, Any]]]], grades: dict[tuple[str, str], int], title: str) -> None:
    print(f"\n{title} ({len(rows)} Themen)")
    print(
        f"{'Weg':36s} {'Haupt 2/1/0':>12s} {'Absätze 2/1/0':>15s} {'gesamt':>7s} {'passend':>8s} {'brauchbar':>10s} "
        f"{'Bausteine':>9s} {'Rückfall':>9s}"
    )
    for way, cell in table(rows, grades).items():
        total = sum(cell["absaetze"]) or 1
        print(
            f"{way:5s}{WAYS[way]:31s} {'/'.join(map(str, cell['haupt'])):>12s} "
            f"{'/'.join(map(str, cell['absaetze'])):>15s} {sum(cell['absaetze']):7d} "
            f"{cell['absaetze'][0] / total * 100:7.0f}% {cell['brauchbar']:5d}/{cell['themen']:<4d} "
            f"{statistics.mean(cell['bausteine']):9.1f} {cell['rueckfall']:9d}"
            + (f"   ohne Note: {len(cell['ohne_note'])}" if cell["ohne_note"] else "")
        )


NORMAL = "--normal" in sys.argv
args = [arg for arg in sys.argv[1:] if arg != "--normal"]
runs = [{row["thema"]: row for row in json.loads(Path(a).read_text(encoding="utf-8"))["themen"]} for a in args[:4]]
m40_rows, m38_rows, m37_rows, r2_rows = runs
rows = [(t, ways_of(m40_rows[t], m38_rows[t], m37_rows[t], r2_rows[t])) for t in m40_rows]
for number, path in enumerate(args[4:6], 1):
    grades = grades_of(Path(path))
    print(f"\n=== Noten {number} ===")
    show(rows, grades, "gewöhnliche Themen (M1)" if NORMAL else "alle")
    for kind in () if NORMAL else ("eigener Artikel", "Gruppe", "Verbindung"):
        show([row for row in rows if kind_of(row[0]) == kind], grades, kind)

for way in LOCAL:
    asked = [m40_rows[t]["wege"][way] for t in m40_rows]
    named = [len(a["genannt"]) + bool(a["uebersicht"]) for a in asked]
    print(
        f"{way}: genannt im Mittel {statistics.mean(named):.1f}, davon im Archiv {statistics.mean(len(a['gefunden']) for a in asked):.1f}; "
        f"ohne gefundenen Artikel {sum(1 for a in asked if not a['gefunden'])}; "
        f"Übersicht = Thema {sum(1 for t, a in zip(m40_rows, asked, strict=True) if a['uebersicht'].lower() == t.lower())}"
    )
