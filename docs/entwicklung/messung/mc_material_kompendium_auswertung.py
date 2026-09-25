"""How the compendium of a material compares with the one of a term (M23): shares of fitting paragraphs and more.

Reads the run of mc_material_kompendium.py and the notes on the articles it printed
(eval/materialwahl/kompendium_noten.yaml: per material and article 2 about the material's topic, 1 related, 0 not).
Per way, apart for the materials with a clear topic and the unsharp ones: compendia made, main article accepted by
the gold, the share of printed paragraphs from fitting (2) and from unfitting (0) articles as the mean over the
compendia made, and usable compendia, whose paragraphs fit at least half; then paragraphs, filled blocks, the
seconds of the LLM question (the compendium's own seconds depend on the order of the ways: the first one per
material reads the archive cold) and tokens. Per material a node way does better or worse than the term when its
share of fitting paragraphs differs by more than ten points, a missing compendium counting as none fitting.
Precision, recall and F1 follow: of the main article against the gold (a way without a compendium loses recall, not
precision), and of the printed articles against the pool of the material, every article with note 2 that any way
printed, as in TREC: an article no way printed stays unknown, and related articles (1) count as not fitting. The
article scores are means over the materials, a missing compendium scoring recall and F1 0; per material a node way
does better or worse than the term when their F1 differ by more than 0.1. Where the articles fit and where not: per
way the main article against the side articles (their notes and their share of the paragraphs), whether KL prints
what B prints when both take the same main article, and what KL and KEa printed together, scored like one way: an
estimate of a combination, not a compendium. For the two materials without a topic it counts the compendia made
anyway. With a second file of notes it prints the agreement of the two raters.

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
from artikelmengen import f1, set_scores
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


def ratio(values: list[float]) -> str:
    return f"{statistics.mean(values):.2f}" if values else "-"


def pool(material: dict[str, Any], notes: Notes) -> set[str]:
    """The articles with note 2 that any way printed for this material: the fitting ones, as far as known."""
    return {
        row["titel"]
        for way in material["wege"].values()
        if way["status"] == "ok"
        for row in way["gedruckt"]
        if notes[(material["node_id"], row["titel"])]["note"] == 2
    }


def article_scores(way: dict[str, Any], fitting: set[str]) -> tuple[float | None, float, float]:
    """Precision (None without a printed article), recall and F1 of the printed articles against the pool."""
    return set_scores({row["titel"] for row in way["gedruckt"]} if way["status"] == "ok" else set(), fitting)


def together(material: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    """What several ways printed for a material, as if one way had: an estimate, not a compendium."""
    rows = [row for n in names if material["wege"][n]["status"] == "ok" for row in material["wege"][n]["gedruckt"]]
    return {"status": "ok", "gedruckt": rows}


def of_notes(values: list[int], note: int) -> str:
    return f"{sum(v == note for v in values) / len(values) * 100:.0f} %" if values else "-"


def accuracy(group: list[dict[str, Any]], pools: dict[str, set[str]]) -> None:
    """Precision, recall and F1 of the main article and of the printed articles, and F1 per material against B."""
    judged = [m for m in group if pools[m["node_id"]]]
    sizes = [float(len(pools[m["node_id"]])) for m in judged]
    print(
        f"Precision, Recall, F1; Artikel gegen die mit Note 2 aus allen Wegen, bei {len(judged)} von {len(group)}, "
        f"je Material Median {median(sizes)}, höchstens {max(sizes, default=0):.0f}"
    )
    scores = {name: [article_scores(m["wege"][name], pools[m["node_id"]]) for m in judged] for name in WAYS}
    for name in WAYS:
        right = [bool(m["wege"][name]["richtig"]) for m in group if m["wege"][name]["status"] == "ok"]
        precision, recall = (sum(right) / len(right) if right else 0.0), sum(right) / len(group)
        print(
            f"{name:4} Hauptartikel P {ratio([float(r) for r in right])} R {recall:.2f} F1 {f1(precision, recall):.2f}"
            f" | Artikel P {ratio([p for p, _, _ in scores[name] if p is not None])} "
            f"R {ratio([r for _, r, _ in scores[name]])} F1 {ratio([f for _, _, f in scores[name]])}"
        )
    for name in WAYS[1:]:
        differences = [node[2] - term[2] for node, term in zip(scores[name], scores["B"], strict=True)]
        print(
            f"{name} gegen den Begriff, F1 der Artikel: besser {sum(d > MARGIN for d in differences)}, "
            f"gleich {sum(abs(d) <= MARGIN for d in differences)}, schlechter {sum(d < -MARGIN for d in differences)}"
        )


def composition(group: list[dict[str, Any]], notes: Notes, pools: dict[str, set[str]]) -> None:
    """Main against side articles per way, whether KL prints what B prints, and KL and KEa together."""
    for name in WAYS:
        made = [(m["node_id"], m["wege"][name]) for m in group if m["wege"][name]["status"] == "ok"]
        if not made:
            print(f"{name:4} kein Kompendium")
            continue
        main = sum(notes.get((node, way["hauptartikel"]), {}).get("note") == 2 for node, way in made)
        side = [
            notes[(node, title)]["note"]
            for node, way in made
            for title in {row["titel"] for row in way["gedruckt"]} - {way["hauptartikel"]}
        ]
        rows = [(row["absaetze"], row["titel"] != way["hauptartikel"]) for _, way in made for row in way["gedruckt"]]
        paragraphs = sum(count for count, _ in rows)
        from_side = f"{sum(c for c, is_side in rows if is_side) / paragraphs * 100:.0f} %" if paragraphs else "-"
        print(
            f"{name:4} Hauptartikel mit Note 2 bei {main} von {len(made)}; Nebenartikel je Kompendium "
            f"{len(side) / len(made):.1f}, Note 2 {of_notes(side, 2)}, Note 0 {of_notes(side, 0)}; Absätze aus "
            f"Nebenartikeln {from_side}"
        )
    same = [
        m
        for m in group
        if m["wege"]["B"]["status"] == m["wege"]["KL"]["status"] == "ok"
        and m["wege"]["KL"]["hauptartikel"] == m["wege"]["B"]["hauptartikel"]
    ]
    alike = sum(m["wege"]["KL"]["gedruckt"] == m["wege"]["B"]["gedruckt"] for m in same)
    print(f"KL mit dem Hauptartikel von B: {len(same)} von {len(group)}, davon dieselben Absätze {alike}")
    judged = [m for m in group if pools[m["node_id"]]]
    both = [together(m, ("KL", "KEa")) for m in judged]
    scores = [article_scores(way, pools[m["node_id"]]) for m, way in zip(judged, both, strict=True)]
    print(
        f"KL und KEa zusammen (Abschätzung): Artikel P {ratio([p for p, _, _ in scores if p is not None])} "
        f"R {ratio([r for _, r, _ in scores])} F1 {ratio([f for _, _, f in scores])}, Artikel je Material "
        f"{statistics.mean(len({row['titel'] for row in way['gedruckt']}) for way in both):.1f}"
    )


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
    pools = {m["node_id"]: pool(m, notes) for m in group}
    accuracy(group, pools)
    composition(group, notes, pools)


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
