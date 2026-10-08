"""Simulation zu M75: wie lange eine Anfrage bei k gleichzeitigen LLM-Aufrufen bräuchte, aus den gemessenen Aufrufen.

Je Lauf von mc_tempo.py (Variante seq) gelten die gemessenen Dauern der Aufrufe und die Reihenfolge der Schritte: die
Aufrufe der Vorbereitung nacheinander, dann die Stapel der Zuordnung, dann die Bausteine des Schreibens, dann Teil 2;
innerhalb eines Schritts laufen höchstens k zugleich, je frei werdender Platz nimmt den nächsten Aufruf (wie
``map_in_threads`` hinter dem Semaphor). Die Zeit ohne LLM (Lesen, Regeln) bleibt, wie gemessen. Je Zahl der Plätze
rechnet sie zweimal: nacheinander wie ausgeliefert, und mit Teil 2 nach der Vorbereitung neben Teil 1, wobei sich beide
die k Plätze teilen. Die Dauern sind die von gpt-6-luna über
OpenAI direkt: Für ein langsameres Modell (academiccloud) ist das Ergebnis eine Untergrenze.

Usage: python mc_tempo_simulation.py <seq_lauf.json> [--plaetze=2,4,10,20] [--json=<out.json>]
"""

from __future__ import annotations

import heapq
import json
import statistics
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

STAGES = {
    "topic_articles": 0, "article_choice": 0, "hit_check": 0, "topic_wording": 0,
    "paragraph_assignment": 1,
    "passage_selection": 2, "section_synthesis": 2, "section_enrichment": 2, "section_coverage": 2,
    "model_knowledge_check": 2,
    "curriculum_check": 3,
}


def duration(call: dict) -> float:
    return sum(a["received"] - a["sent"] for a in call.get("attempts") or [])


def makespan(durations: list[float], slots: int, start: float = 0.0, busy: list[float] | None = None) -> float:
    """When the last of ``durations`` ends, each started on the first free of ``slots`` places from ``start``."""
    free = sorted(busy or [])[:slots]
    free += [start] * (slots - len(free))
    heapq.heapify(free)
    end = start
    for length in durations:
        begin = max(heapq.heappop(free), start)
        heapq.heappush(free, begin + length)
        end = max(end, begin + length)
    return end


def simulate(run: dict, slots: int, parallel: bool) -> float:
    stages: dict[int, list[float]] = {0: [], 1: [], 2: [], 3: []}
    for call in run.get("calls") or []:
        stages[STAGES.get(call.get("prompt") or "", 0)].append(duration(call))
    llm_measured = 0.0
    for stage, durations in stages.items():
        if durations:
            llm_measured += makespan(durations, 1000) if stage else sum(durations)
    rules = max(0.0, run["s"] - llm_measured)  # reading and rules, as measured
    t = sum(stages[0])  # the preparation asks one after another
    if parallel and stages[3]:
        # part 2 starts beside part 1 after the preparation; both share the places
        part1_end = makespan(stages[1], slots, t)
        part1_end = makespan(stages[2], slots, part1_end)
        part2_end = makespan(stages[3], slots, t)
        return rules + max(part1_end, part2_end)
    for stage in (1, 2, 3):
        if stages[stage]:
            t = makespan(stages[stage], slots, t)
    return rules + t


def table(runs: list[dict], places: list[int]) -> list[dict]:
    """Per profile the measured median and, per number of places, the simulated medians in sequence and in parallel."""
    rows = []
    for profile in ("best-quality", "best-quality-generated", "best-coverage-generated"):
        group = [r for r in runs if r["profile"] == profile]
        if not group:
            continue
        row = {"profile": profile, "measured_s": round(statistics.median(r["s"] for r in group), 1), "places": {}}
        for k in places:
            row["places"][k] = {
                "seq_s": round(statistics.median(simulate(r, k, False) for r in group), 1),
                "par_s": round(statistics.median(simulate(r, k, True) for r in group), 1),
            }
        rows.append(row)
    return rows


def main() -> None:
    path = Path(next(a for a in sys.argv[1:] if not a.startswith("--")))
    places = [int(p) for p in next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--plaetze=")),
                                   "2,4,10,20").split(",")]
    out = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--json=")), None)
    runs = [r for r in json.loads(path.read_text(encoding="utf-8")) if not r.get("error") and r.get("calls")]
    rows = table(runs, places)
    for row in rows:
        cells = [f"k={k}: {v['seq_s']} s, mit Teil 2 parallel {v['par_s']} s" for k, v in row["places"].items()]
        print(f"{row['profile']}: gemessen {row['measured_s']} s | " + " | ".join(cells))
    if out:
        Path(out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
