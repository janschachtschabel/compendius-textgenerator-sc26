"""M38 evaluated: set-like topics without a large LLM, next to the ways of M37, from the blind article grades.

Per way the grade of the main article, the paragraphs printed from articles graded 2, 1 and 0, the compendia of which
at least half the printed paragraphs come from articles graded 2 ("brauchbar", as M23 and M37), the filled blocks and
what finding the articles cost: P's own seconds, the small models' question in seconds and tokens. B and N come from
the run of M37 on the same topics; R ran again in M38 and has to print what it printed in M37, else the grades of M37
would not carry over - the script says how many topics agree.

Usage (from the project folder):
python mc_sammelthemen_ohne_llm_auswertung.py <m38 run.json> <m37 run.json> <grades.yaml> [<second.yaml>] [--normal]
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
    "R": "llm-free heute (M38)",
    "B": "balanced heute (M37)",
    "N": "N mit gpt-6-luna (M37)",
    "P": "ohne LLM: Parse und Archiv",
    "L8": "N mit llama-3.1-8b",
    "Q30": "N mit qwen3-30b-a3b",
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


def grades_of(path: Path) -> dict[tuple[str, str], int]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {(entry["thema"], entry["artikel"]): int(entry["note"]) for entry in data["noten"]}


def ways_of(m38: dict[str, Any], m37: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every way's result for one topic: R, P and the small models from M38, B and N from M37.

    Where a small model named no article the archive has, the service would fall back to balanced as it is; that
    fallback counts, so a model that fails is not measured on its good topics only.
    """
    ways = {w: m38["wege"][w] for w in ("R", "P", "L8", "Q30")}
    for way in ("L8", "Q30"):
        if "hauptartikel" not in ways[way]:
            ways[way] = {**m37["wege"]["B"], "rueckfall": True}
    return {**ways, "B": m37["wege"]["B"], "N": m37["wege"]["N"]}


def table(rows: list[tuple[str, dict[str, dict[str, Any]]]], grades: dict[tuple[str, str], int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for way in WAYS:
        cell: dict[str, Any] = {"haupt": [0, 0, 0], "absaetze": [0, 0, 0], "brauchbar": 0, "themen": 0,
                                "bausteine": [], "ohne_note": []}  # fmt: skip
        for topic, ways in rows:
            result = ways[way]
            if "hauptartikel" not in result:
                continue
            cell["themen"] += 1
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
        f"{'Weg':34s} {'Haupt 2/1/0':>12s} {'Absätze 2/1/0':>15s} {'passend':>8s} {'brauchbar':>10s} {'Bausteine':>9s}"
    )
    for way, cell in table(rows, grades).items():
        total = sum(cell["absaetze"]) or 1
        print(
            f"{way:4s}{WAYS[way]:30s} {'/'.join(map(str, cell['haupt'])):>12s} "
            f"{'/'.join(map(str, cell['absaetze'])):>15s} "
            f"{cell['absaetze'][0] / total * 100:7.0f}% {cell['brauchbar']:5d}/{cell['themen']:<4d} "
            f"{statistics.mean(cell['bausteine'] or [0]):9.1f}"
            + (f"   ohne Note: {len(cell['ohne_note'])}" if cell["ohne_note"] else "")
        )


NORMAL = "--normal" in sys.argv
args = [arg for arg in sys.argv[1:] if arg != "--normal"]
m38_rows = {row["thema"]: row for row in json.loads(Path(args[0]).read_text(encoding="utf-8"))["themen"]}
m37_rows = {row["thema"]: row for row in json.loads(Path(args[1]).read_text(encoding="utf-8"))["themen"]}
rows = [(topic, ways_of(m38_rows[topic], m37_rows[topic])) for topic in m38_rows]
same_r = sum(
    [e["titel"] for e in m38_rows[t]["wege"]["R"]["gedruckt"]]
    == [e["titel"] for e in m37_rows[t]["wege"]["R"]["gedruckt"]]
    for t in m38_rows
)
print(f"R druckt wie in M37 bei {same_r} von {len(m38_rows)} Themen")
for number, path in enumerate(args[2:4], 1):
    grades = grades_of(Path(path))
    print(f"\n=== Noten {number} ===")
    show(rows, grades, "gewöhnliche Themen (M1)" if NORMAL else "alle")
    for kind in () if NORMAL else ("eigener Artikel", "Gruppe", "Verbindung"):
        show([row for row in rows if kind_of(row[0]) == kind], grades, kind)

found = [m38_rows[t]["wege"]["P"]["verfahren"] for t in m38_rows]
applied = [f for f in found if f["sekunden"] > 0]
seconds = [f["sekunden"] for f in applied] or [0.0]
print(
    f"\nP greift bei {len(applied)} von {len(found)} Themen; Sekunden im Median {statistics.median(seconds):.2f}, "
    f"höchstens {max(seconds):.2f}"
)
for way in ("L8", "Q30"):
    asked = [m38_rows[t]["wege"][way] for t in m38_rows]
    print(
        f"{way}: Frage im Median {statistics.median(a['sekunden_frage'] for a in asked):.2f} s "
        f"(höchstens {max(a['sekunden_frage'] for a in asked):.2f}), "
        f"{statistics.median(a['tokens_frage'] for a in asked):.0f} Tokens; "
        f"ohne gefundenen Artikel: {sum(1 for a in asked if not a['gefunden'])}"
    )
