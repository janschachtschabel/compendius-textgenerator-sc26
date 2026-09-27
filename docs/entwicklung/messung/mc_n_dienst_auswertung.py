"""M39 evaluated: N built into balanced (C) next to the ways of M37 on the same topics, from the blind grades.

Per way the grade of the main article, the paragraphs printed from articles graded 2, 1 and 0, the compendia of which at
least half the printed paragraphs come from articles graded 2 ("brauchbar", as M23 and M37) and the blocks filled.
R, B and N (the prototype) are the runs of M37; C is the service with N built in (mc_n_dienst.py).

Usage (from the project folder):
python mc_n_dienst_auswertung.py <m39.json> <m37.json> <grades.yaml> [<second.yaml>]
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
    "R": "llm-free (M37)",
    "B": "balanced vor D63 (M37)",
    "N": "N als Prototyp (M37)",
    "C": "balanced mit N (D63)",
}


def grades_of(path: Path) -> dict[tuple[str, str], int]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {(entry["thema"], entry["artikel"]): int(entry["note"]) for entry in data["noten"]}


m39 = {row["thema"]: row["wege"]["C"] for row in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["themen"]}
m37 = {row["thema"]: row["wege"] for row in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["themen"]}
for number, path in enumerate(sys.argv[3:5], 1):
    grades = grades_of(Path(path))
    print(f"\n=== Noten {number} ({len(m39)} Themen) ===")
    print(f"{'Weg':30s} {'Haupt 2/1/0':>12s} {'Absätze 2/1/0':>15s} {'gesamt':>7s} {'passend':>8s} {'brauchbar':>10s} "
          f"{'Bausteine':>9s}")  # fmt: skip
    for way, label in WAYS.items():
        main, printed, usable, blocks, missing = [0, 0, 0], [0, 0, 0], 0, [], 0
        for topic, ways in m37.items():
            result: dict[str, Any] = m39[topic] if way == "C" else ways[way]
            note = grades.get((topic, result["hauptartikel"]))
            if note is not None:
                main[2 - note] += 1
            own = [0, 0, 0]
            for entry in result["gedruckt"]:
                note = grades.get((topic, entry["titel"]))
                if note is None:
                    missing += 1
                    note = 0
                own[2 - note] += entry["absaetze"]
            printed = [a + b for a, b in zip(printed, own, strict=True)]
            usable += sum(own) > 0 and own[0] * 2 >= sum(own)
            blocks.append(result["bausteine"])
        total = sum(printed) or 1
        print(
            f"{way:3s}{label:27s} {'/'.join(map(str, main)):>12s} {'/'.join(map(str, printed)):>15s} {sum(printed):7d} "
            f"{printed[0] / total * 100:7.0f}% {usable:5d}/{len(m37):<4d} {statistics.mean(blocks):9.1f}"
            + (f"   ohne Note: {missing}" if missing else "")
        )
