"""Auswertung zu M75 (mc_tempo.py): je Profil und Variante, wohin Zeit und Tokens gehen.

Je Lauf werden die LLM-Aufrufe nach Schritt gruppiert - Vorbereitung (Artikelwahl, Prüfung der Treffer,
Themenformulierung), Zuordnung, Schreiben, Teil 2 (Prüfung der Lehrplanelemente) - und je Gruppe gezählt: Aufrufe,
Spanne vom ersten Stellen bis zur letzten Antwort, Wartezeit vor dem freien Platz (gestellt bis gesendet), Dauer der
Aufrufe, Eingabe-Tokens mit dem Anteil aus dem Cache, Ausgabe-Tokens mit dem Anteil fürs Denken. Ausgegeben werden
Mediane je Profil über die Themen.

Usage: python mc_tempo_auswertung.py <lauf.json> [<lauf.json> ...] [--json=<out.json>]
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

GROUPS = {
    "topic_articles": "vorbereitung",
    "article_choice": "vorbereitung",
    "hit_check": "vorbereitung",
    "topic_wording": "vorbereitung",
    "node_topic": "vorbereitung",
    "node_topic_with_topic": "vorbereitung",
    "paragraph_assignment": "zuordnung",
    "passage_selection": "schreiben",
    "section_synthesis": "schreiben",
    "section_enrichment": "schreiben",
    "section_coverage": "schreiben",
    "model_knowledge_check": "schreiben",
    "curriculum_check": "teil2",
}
ORDER = ["vorbereitung", "zuordnung", "schreiben", "teil2"]
PROFILES = ["llm-free", "balanced", "best-quality", "best-quality-generated", "best-coverage-generated"]


def duration(call: dict) -> float:
    attempts = call.get("attempts") or []
    return attempts[-1]["received"] - attempts[-1]["sent"] if attempts else call["done"] - call["asked"]


def wait(call: dict) -> float:
    attempts = call.get("attempts") or []
    return max(0.0, attempts[0]["sent"] - call["asked"]) if attempts else 0.0


def total(call: dict, field: str) -> int:
    return sum(a.get(field) or 0 for a in call.get("attempts") or [])


def groups_of(run: dict) -> dict[str, dict]:
    calls_by: dict[str, list[dict]] = defaultdict(list)
    for call in run.get("calls") or []:
        calls_by[GROUPS.get(call.get("prompt") or "", "sonst")].append(call)
    result = {}
    for name, calls in calls_by.items():
        result[name] = {
            "calls": len(calls),
            "span": round(max(c["done"] for c in calls) - min(c["asked"] for c in calls), 2),
            "first": round(min(c["asked"] for c in calls), 2),
            "last": round(max(c["done"] for c in calls), 2),
            "wait_max": round(max(wait(c) for c in calls), 2),
            "wait_sum": round(sum(wait(c) for c in calls), 2),
            "waited": sum(1 for c in calls if wait(c) > 0.2),
            "dur_median": round(statistics.median(duration(c) for c in calls), 2),
            "dur_max": round(max(duration(c) for c in calls), 2),
            "prompt": sum(total(c, "prompt") for c in calls),
            "cached": sum(total(c, "cached") for c in calls),
            "completion": sum(total(c, "completion") for c in calls),
            "reasoning": sum(total(c, "reasoning") for c in calls),
            "retries": sum(max(0, len(c.get("attempts") or []) - 1) for c in calls),
            "errors": sum(1 for c in calls if c.get("error")),
            "prompts": sorted({c.get("prompt") or "" for c in calls}),
        }
    return result


def peak(run: dict) -> int:
    """The most calls in flight at once (sent to received)."""
    events = []
    for call in run.get("calls") or []:
        for attempt in call.get("attempts") or []:
            events += [(attempt["sent"], 1), (attempt["received"], -1)]
    level = best = 0
    for _, step in sorted(events):
        level += step
        best = max(best, level)
    return best


def median(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def main() -> None:
    paths = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
    out = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--json=")), None)
    runs = [run for path in paths for run in json.loads(path.read_text(encoding="utf-8"))]
    by_setup: dict[tuple, list[dict]] = defaultdict(list)
    for run in runs:
        if run.get("error"):
            print(f"! {run['topic']} | {run['profile']} | {run['variant']}: {run['error']}")
            continue
        by_setup[(run["profile"], run["variant"], run["concurrency"])].append(run)
    summary = []
    for (profile, variant, concurrency), group in sorted(
        by_setup.items(), key=lambda item: (PROFILES.index(item[0][0]), item[0][1], item[0][2])
    ):
        parts = [groups_of(run) for run in group]
        row = {
            "profile": profile, "variant": variant, "concurrency": concurrency, "runs": len(group),
            "s": median([run["s"] for run in group]),
            "s_range": [min(run["s"] for run in group), max(run["s"] for run in group)],
            "tokens": median([(run.get("tokens") or {}).get("total") or 0 for run in group]),
            "cached": median([(run.get("tokens") or {}).get("cached") or 0 for run in group]),
            "peak": median([peak(run) for run in group]),
            "timings": {
                stage: median([(run.get("timings") or {}).get(stage) for run in group])
                for stage in sorted({stage for run in group for stage in (run.get("timings") or {})})
            },
            "groups": {},
        }
        for name in ORDER + ["sonst"]:
            present = [p[name] for p in parts if name in p]
            if not present:
                continue
            row["groups"][name] = {
                key: median([p[key] for p in present])
                for key in ("calls", "span", "first", "last", "wait_max", "wait_sum", "waited", "dur_median",
                            "dur_max", "prompt", "cached", "completion", "reasoning", "retries", "errors")
            }
        summary.append(row)
        print(f"\n== {profile} | {variant} | c{concurrency} | {len(group)} Läufe | {row['s']} s "
              f"({row['s_range'][0]}-{row['s_range'][1]}) | Tokens {row['tokens']} davon Cache {row['cached']} | "
              f"höchstens {row['peak']} Aufrufe zugleich")
        print("   Zeiten (ms):", row["timings"])
        for name, values in row["groups"].items():
            print(f"   {name:12} Aufrufe {values['calls']} | ab {values['first']} s bis {values['last']} s "
                  f"(Spanne {values['span']} s) | Dauer Median {values['dur_median']} max {values['dur_max']} s | "
                  f"gewartet {values['waited']} Aufrufe, max {values['wait_max']} s | Eingabe {values['prompt']} "
                  f"(Cache {values['cached']}) | Ausgabe {values['completion']} (Denken {values['reasoning']}) | "
                  f"Wiederholungen {values['retries']}, Fehler {values['errors']}")
    if out:
        Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
