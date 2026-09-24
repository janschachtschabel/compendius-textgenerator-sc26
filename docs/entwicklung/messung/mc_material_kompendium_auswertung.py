"""How the compendium of a material compares with the one of a term (M23): shares of fitting paragraphs and more.

Reads the run of mc_material_kompendium.py and the notes on the articles it printed
(eval/materialwahl/kompendium_noten.yaml: per material and article 2 about the material's topic, 1 related, 0 not).
Per way, apart for the materials with a clear topic and the unsharp ones: compendia made, main article accepted by
the gold, the share of printed paragraphs from fitting (2) and from unfitting (0) articles as the mean over the
compendia made, and usable compendia, whose paragraphs fit at least half; then paragraphs, filled blocks, the
seconds of the LLM question (the compendium's own seconds depend on the order of the ways: the first one per
material reads the archive cold) and tokens. Per material a node way does better or worse than the term when its
share of fitting paragraphs differs by more than ten points, a missing compendium counting as none fitting. For the
two materials without a topic it counts the compendia made anyway. With a second file of notes it prints the
agreement of the two raters.

Usage (project venv, from the project root):
python docs/entwicklung/messung/mc_material_kompendium_auswertung.py <m23.json> <notes.yaml> [<second notes.yaml>]
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

WAYS = ("B", "K0", "K0b", "KL", "KEl", "KEa")
USABLE = 0.5  # a compendium whose paragraphs fit at least half
MARGIN = 0.1  # better or worse than the term: more than ten points of fitting paragraphs apart

Notes = dict[tuple[str, str], dict[str, Any]]


def load_notes(path: Path) -> Notes:
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["noten"]
    return {(entry["node_id"], entry["artikel"]): entry for entry in entries}


def shares(way: dict[str, Any], node_id: str, notes: Notes) -> tuple[float, float] | None:
    """Fitting and unfitting share of the printed paragraphs; None without a compendium or paragraph."""
    if way["status"] != "ok":
        return None
    printed = [(row["absaetze"], notes[(node_id, row["titel"])]["note"]) for row in way["gedruckt"]]
    total = sum(count for count, _ in printed)
    if not total:
        return None
    return sum(c for c, note in printed if note == 2) / total, sum(c for c, note in printed if note == 0) / total


def median(values: list[float]) -> str:
    return f"{statistics.median(values):.1f}" if values else "-"


def percent(values: list[float]) -> str:
    return f"{statistics.mean(values) * 100:3.0f} %" if values else "   -"


def report(materials: list[dict[str, Any]], notes: Notes, art: str) -> None:
    group = [m for m in materials if m["art"] == art]
    print(f"\n== {art}: {len(group)} Materialien")
    print("Weg  gemacht  Hauptartikel  passend  unpassend  brauchbar  Absätze  Bausteine  LLM-Frage s  Tokens")
    for name in WAYS:
        ways = [m["wege"][name] for m in group]
        made = [w for w in ways if w["status"] == "ok"]
        found = [s for m in group if (s := shares(m["wege"][name], m["node_id"], notes)) is not None]
        right = sum(bool(w.get("richtig")) for w in made)
        seconds = [w["sekunden_frage"] for w in made if "tokens_frage" in w]
        tokens = [w.get("tokens_dienst", 0) + w.get("tokens_frage", 0) for w in ways]
        print(
            f"{name:4} {len(made):3}/{len(group):<3} {right:6}/{len(group):<6} {percent([f for f, _ in found]):>7}  "
            f"{percent([o for _, o in found]):>8}  {sum(f >= USABLE for f, _ in found):6}/{len(group):<3} "
            f"{median([sum(r['absaetze'] for r in w['gedruckt']) for w in made]):>7}  "
            f"{median([w['bausteine'] for w in made]):>8}  {median(seconds):>11}  {statistics.mean(tokens):6.0f}"
        )
    for name in ("KEl", "KEa"):
        among = sum(any(e in m["akzeptiert"] for e in m["wege"][name].get("entitaeten", [])) for m in group)
        print(f"{name}: ein akzeptierter Artikel unter den Entitäten bei {among} von {len(group)}")
    for name in WAYS[1:]:
        verdict = {"besser": 0, "gleich": 0, "schlechter": 0}
        for m in group:
            term = shares(m["wege"]["B"], m["node_id"], notes)
            node = shares(m["wege"][name], m["node_id"], notes)
            difference = (node[0] if node else 0.0) - (term[0] if term else 0.0)
            key = "besser" if difference > MARGIN else "schlechter" if difference < -MARGIN else "gleich"
            verdict[key] += 1
        print(f"{name} gegen den Begriff: " + ", ".join(f"{k} {v}" for k, v in verdict.items()))


def main() -> None:
    materials = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    for index, path in enumerate(sys.argv[2:4]):
        notes = load_notes(Path(path))
        print(f"\n######## Noten: {path}")
        for art in ("klar", "unscharf"):
            report(materials, notes, art)
        none = [m for m in materials if m["art"] == "keins"]
        made = {name: sum(m["wege"][name]["status"] == "ok" for m in none) for name in WAYS}
        print(f"\nohne Thema ({len(none)}): trotzdem ein Kompendium " + ", ".join(f"{k} {v}" for k, v in made.items()))
        if index == 1:
            agreement(load_notes(Path(sys.argv[2])), notes)


main()
