"""Precision of part 2 with and without the subject (M22), from the sample of mc_lehrplan_treffer.py and its notes.

Per topic, the notes of each stratum estimate the share of fitting elements: of the run with the subject from its
own stratum, of the run without it from both, weighted by how many elements each stratum holds (the run with the
subject prints a subset of the other). "passend" counts note 2, "mindestens berührt" notes 1 and 2. The means are
over topics, each request counting once; the elements a run prints in all topics are summed as well.

With a second file of notes on the same elements it prints the agreement of the two raters.

Usage (project venv, from the project root):
python docs/entwicklung/messung/mc_lehrplan_auswertung.py <m22.json> <notes.yaml> [<second notes.yaml>]
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def load_notes(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["noten"]
    return {(entry["thema"], entry["iri"]): entry for entry in entries}


def share(notes: list[int], least: int) -> float | None:
    return sum(note >= least for note in notes) / len(notes) if notes else None


def estimate(topic: dict[str, Any], notes: dict[tuple[str, str], dict[str, Any]], least: int) -> dict[str, Any]:
    """Share of fitting elements of both runs and the fitting elements the subject drops, for one topic."""
    by_stratum: dict[str, list[int]] = {"mit_fach": [], "nur_ohne": []}
    for row in topic["stichprobe"]:
        by_stratum[row["schicht"]].append(notes[(topic["thema"], row["iri"])]["note"])
    n_with, n_without = topic["mit_fach"]["elemente"], topic["ohne_fach"]["elemente"]
    n_only = n_without - n_with
    p_with, p_only = share(by_stratum["mit_fach"], least), share(by_stratum["nur_ohne"], least)
    fitting_with = n_with * p_with if p_with is not None else 0.0
    fitting_only = n_only * p_only if p_only is not None else 0.0
    return {
        "with": p_with,
        "without": (fitting_with + fitting_only) / n_without if n_without else None,
        "fitting_with": fitting_with,
        "fitting_without": fitting_with + fitting_only,
        "only_without": p_only,
    }


def mean(values: list[float | None]) -> float:
    return statistics.mean(value for value in values if value is not None)


def percent(value: float | None) -> str:
    return "  -" if value is None else f"{value * 100:3.0f}"


def report(topics: list[dict[str, Any]], notes: dict[tuple[str, str], dict[str, Any]], name: str) -> None:
    print(f"\n== {name}")
    print(f"{'Thema':24} {'ohne':>5} {'mit':>4} | passend: ohne mit nur-ohne | mind. berührt: ohne mit")
    strict = [estimate(topic, notes, 2) for topic in topics]
    lenient = [estimate(topic, notes, 1) for topic in topics]
    for topic, s, s1 in zip(topics, strict, lenient, strict=True):
        print(
            f"{topic['thema']:24} {topic['ohne_fach']['elemente']:5} {topic['mit_fach']['elemente']:4} | "
            f"{percent(s['without']):>12} {percent(s['with']):>3} {percent(s['only_without']):>8} | "
            f"{percent(s1['without']):>18} {percent(s1['with']):>3}"
        )
    for label, rows in (("passend", strict), ("mindestens berührt", lenient)):
        kept = sum(row["fitting_with"] for row in rows) / sum(row["fitting_without"] for row in rows)
        print(
            f"{label}: Mittel über Themen ohne Fach {mean([r['without'] for r in rows]) * 100:.0f} %, "
            f"mit Fach {mean([r['with'] for r in rows]) * 100:.0f} %; "
            f"der Fachfilter behält {kept * 100:.0f} % der {label}en Elemente "
            f"(geschätzt {sum(r['fitting_with'] for r in rows):.0f} von {sum(r['fitting_without'] for r in rows):.0f})"
        )
    print(
        f"Elemente in allen Themen: ohne Fach {sum(t['ohne_fach']['elemente'] for t in topics)}, "
        f"mit Fach {sum(t['mit_fach']['elemente'] for t in topics)}"
    )
    for run in ("ohne_fach", "mit_fach"):
        parent = sum(topic[run]["fundort"].get("parent", 0) for topic in topics)
        print(f"{run}: nur in der Überschrift gefunden {parent} von {sum(topic[run]['elemente'] for topic in topics)}")
    by_kind: dict[str, list[int]] = {
        "Stichwort ist das Thema selbst": [],
        "Stichwort ist ein anderes": [],
        "Treffer im Element": [],
        "Treffer nur in der Überschrift": [],
    }
    reasons: dict[str, Counter[str]] = {"mit_fach": Counter(), "nur_ohne": Counter()}
    for topic in topics:
        first = topic["ohne_fach"]["stichwoerter"][0].casefold()
        for row in topic["stichprobe"]:
            entry = notes[(topic["thema"], row["iri"])]
            kind = (
                "Stichwort ist das Thema selbst"
                if row["stichwort"].casefold() == first
                else "Stichwort ist ein anderes"
            )
            by_kind[kind].append(entry["note"])
            by_kind["Treffer im Element" if row["fundort"] == "label" else "Treffer nur in der Überschrift"].append(
                entry["note"]
            )
            if entry["note"] == 0:
                reasons[row["schicht"]][entry.get("grund", "?")] += 1
    for kind, values in by_kind.items():
        print(
            f"Stichprobe, {kind}: {len(values)} Elemente, passend {percent(share(values, 2))} %, "
            f"mindestens berührt {percent(share(values, 1))} %"
        )
    for stratum, counts in reasons.items():
        print(f"Gründe der Note 0, Schicht {stratum}: {dict(counts.most_common())}")


def agreement(first: dict[tuple[str, str], dict[str, Any]], second: dict[tuple[str, str], dict[str, Any]]) -> None:
    keys = sorted(first)
    assert keys == sorted(second), "the two files must note the same elements"
    pairs = [(first[key]["note"], second[key]["note"]) for key in keys]
    observed = sum(a == b for a, b in pairs) / len(pairs)
    first_counts, second_counts = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first_counts[note] * second_counts[note] for note in (0, 1, 2)) / len(pairs) ** 2
    kappa = (observed - expected) / (1 - expected)
    same_fit = sum((a == 2) == (b == 2) for a, b in pairs) / len(pairs)
    same_zero = sum((a == 0) == (b == 0) for a, b in pairs) / len(pairs)
    print(
        f"\nÜbereinstimmung auf {len(pairs)} Elementen: gleiche Note {observed * 100:.0f} % "
        f"(Cohens Kappa {kappa:.2f}), einig über passend {same_fit * 100:.0f} %, "
        f"einig über Note 0 {same_zero * 100:.0f} %"
    )
    print("Kreuztabelle (Zeile erste, Spalte zweite Note):")
    table = Counter(pairs)
    for a in (0, 1, 2):
        print(f"  {a}: " + "  ".join(f"{table[(a, b)]:3}" for b in (0, 1, 2)))


topics = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
first_notes = load_notes(Path(sys.argv[2]))
report(topics, first_notes, sys.argv[2])
if len(sys.argv) > 3:
    second_notes = load_notes(Path(sys.argv[3]))
    report(topics, second_notes, sys.argv[3])
    agreement(first_notes, second_notes)
