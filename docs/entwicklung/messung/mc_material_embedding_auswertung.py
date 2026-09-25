"""How close static embeddings come to the article of a real material without an LLM (M24): the evaluation.

Reads the run of mc_material_embedding.py and the notes of M23 (eval/materialwahl/kompendium_noten.yaml), whose
articles with note 2 are the fitting ones known per material. Per way, apart for the materials with a clear topic and
the unsharp ones: the first hit as main article against the gold (precision over the materials the way answered,
recall over all, F1), how often an accepted article is among the first 3, 10 and 20, the median rank of the first
accepted one where it is among the 20, and the share of the known fitting articles among the first 10 and 20 (a hit
nobody judged counts as not fitting). For the two materials without a topic the similarity of their first hit against
the median of the clear materials, then the timings of the run.

Usage (project venv, from the project root):
python docs/entwicklung/messung/mc_material_embedding_auswertung.py <m24.json> <notes.yaml>
"""

from __future__ import annotations

import json
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from artikelmengen import f1, set_scores

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

WAYS = ("D1", "D1k", "D2", "D2k", "E", "BD1", "BD2")
STAGES = ("D1", "D1k", "D2", "D2k")  # the ways a material without a topic runs through


Notes = dict[tuple[str, str], int]


def load_notes(path: Path) -> Notes:
    return {(e["node_id"], e["artikel"]): e["note"] for e in yaml.safe_load(path.read_text(encoding="utf-8"))["noten"]}


def fitting(notes: Notes) -> dict[str, set[str]]:
    """Per material the articles of M23 with note 2."""
    pools: dict[str, set[str]] = {}
    for (node_id, title), note in notes.items():
        if note == 2:
            pools.setdefault(node_id, set()).add(title)
    return pools


def rank(hits: list[list[Any]], accepted: set[str]) -> int | None:
    return next((i for i, (title, _) in enumerate(hits, 1) if title in accepted), None)


def number(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def report(group: list[dict[str, Any]], pools: dict[str, set[str]]) -> None:
    judged = [m for m in group if pools.get(m["node_id"])]
    for name in WAYS:
        answered = sum(bool(m["wege"][name]["treffer"]) for m in group)
        ranks = [rank(m["wege"][name]["treffer"], set(m["akzeptiert"])) for m in group]
        found = [r for r in ranks if r is not None]
        right = sum(r == 1 for r in found)
        precision, recall = (right / answered if answered else None), right / len(group)
        pool = {
            k: [
                len({title for title, _ in m["wege"][name]["treffer"][:k]} & pools[m["node_id"]])
                / len(pools[m["node_id"]])
                for m in judged
            ]
            for k in (10, 20)
        }
        print(
            f"{name:4} Hauptartikel P {number(precision)} R {recall:.2f} F1 {f1(precision or 0.0, recall):.2f} | "
            f"unter 3: {sum(r <= 3 for r in found)}, unter 10: {sum(r <= 10 for r in found)}, "
            f"unter 20: {len(found)} | Rang {f'{statistics.median(found):.1f}' if found else '-'} "
            f"(gefunden {len(found)}) | Pool unter 10: {number(mean(pool[10]))}, unter 20: {number(mean(pool[20]))}"
        )


def first(material: dict[str, Any], name: str) -> float | None:
    hits = material["wege"][name]["treffer"]
    return hits[0][1] if hits else None


def without_topic(materials: list[dict[str, Any]]) -> None:
    """Whether a material without a topic stands out by a weak first hit: a threshold would be option D of M23."""
    for m in materials:
        if m["art"] == "keins":
            print(
                f"ohne Thema: {m['titel'][:40]}: erster Treffer "
                + ", ".join(f"{name} {number(first(m, name))}" for name in STAGES)
            )
    clear = [m for m in materials if m["art"] == "klar"]
    medians = {name: [s for m in clear if (s := first(m, name)) is not None] for name in STAGES}
    print(
        "Median der ersten Treffer, klar: "
        + ", ".join(f"{name} {number(statistics.median(v) if v else None)}" for name, v in medians.items())
    )


def auc(positive: list[float], negative: list[float]) -> float:
    """The chance that a positive article is closer to the material than a negative one, ties counting half."""
    wins = sum((p > n) + 0.5 * (p == n) for p in positive for n in negative)
    return wins / (len(positive) * len(negative))


def separation(materials: list[dict[str, Any]], notes: Notes) -> None:
    """Whether the similarity to the material sorts the articles of M23 by their note: a filter without an LLM."""
    similar = {m["node_id"]: m.get("aehnlichkeit", {}) for m in materials}
    by_note: dict[int, list[float]] = {0: [], 1: [], 2: []}
    for (node_id, title), note in notes.items():
        value = similar.get(node_id, {}).get(title)
        if value is not None:
            by_note[note].append(value)
    measured = sum(len(values) for values in by_note.values())
    print(
        f"Ähnlichkeit zum Material, {measured} Artikel ({len(notes) - measured} ohne Ähnlichkeit): Mittel "
        + ", ".join(f"Note {note} {number(mean(values))}" for note, values in by_note.items())
    )
    if not by_note[0] or not by_note[2]:
        return
    print(
        f"AUC passend gegen unpassend {auc(by_note[2], by_note[0]):.2f}, "
        f"nicht unpassend gegen unpassend {auc(by_note[2] + by_note[1], by_note[0]):.2f}"
    )
    threshold = sorted(by_note[2])[int(0.1 * len(by_note[2]))]
    below = {note: sum(v < threshold for v in values) / len(values) for note, values in by_note.items() if values}
    print(
        f"Schwelle {threshold:.2f} (10-%-Rang der passenden): darunter "
        + ", ".join(f"Note {note} {share * 100:.0f} %" for note, share in below.items())
    )


SUBSETS: dict[str, Callable[[list[str]], bool]] = {
    "Zusatzartikel der alten Entitäten (KEa, nicht KL)": lambda ways: "KEa" in ways and "KL" not in ways,
    "Nebenartikel des LLM-Themas (KL)": lambda ways: "KL" in ways,
}


def share_of(values: list[int], note: int) -> str:
    return f"{sum(v == note for v in values) / len(values) * 100:.0f} %" if values else "-"


def linking(materials: list[dict[str, Any]], notes: Notes) -> None:
    """Whether a link with the main article of the LLM topic keeps the fitting articles and drops the unfitting."""
    for label, chosen in SUBSETS.items():
        rows = []
        for m in materials:
            anchor = m.get("anker")
            for title, ways in m.get("gedruckt_von", {}).items():
                linked, note = m["verlinkt"].get(title), notes.get((m["node_id"], title))
                if anchor and title != anchor and chosen(ways) and linked is not None and note is not None:
                    rows.append((linked, note))
        linked_notes = [note for linked, note in rows if linked]
        unlinked_notes = [note for linked, note in rows if not linked]
        fitting = [linked for linked, note in rows if note == 2]
        unfitting = [not linked for linked, note in rows if note == 0]
        print(
            f"{label}: {len(rows)} Artikel | verlinkt {len(linked_notes)}: Note 2 {share_of(linked_notes, 2)}, "
            f"Note 0 {share_of(linked_notes, 0)} | nicht verlinkt {len(unlinked_notes)}: Note 2 "
            f"{share_of(unlinked_notes, 2)}, Note 0 {share_of(unlinked_notes, 0)} | nur verlinkte: behält Note 2 "
            f"{share_of([int(k) for k in fitting], 1)}, entfernt Note 0 {share_of([int(r) for r in unfitting], 1)}"
        )


COMBINATIONS: dict[str, Callable[[list[str], bool | None], bool]] = {
    "KL": lambda ways, linked: "KL" in ways,
    "KL und alle Entitäten des alten Dienstes": lambda ways, linked: "KL" in ways or "KEa" in ways,
    "KL und die mit KL verlinkten": lambda ways, linked: "KL" in ways or ("KEa" in ways and linked is True),
}


def combination(group: list[dict[str, Any]], pools: dict[str, set[str]], art: str) -> None:
    """KL alone, with every article of the old entities, and with those that link with its main article: estimated
    from what M23 printed, as M23 estimated the union, not a compendium built."""
    judged = [m for m in group if pools.get(m["node_id"]) and m.get("anker")]
    parts = []
    for label, keep in COMBINATIONS.items():
        scores = [
            set_scores(
                {t for t, ways in m["gedruckt_von"].items() if keep(ways, m["verlinkt"].get(t))}, pools[m["node_id"]]
            )
            for m in judged
        ]
        parts.append(
            f"{label} P {number(mean([p for p, _, _ in scores if p is not None]))} "
            f"R {number(mean([r for _, r, _ in scores]))} F1 {number(mean([f for _, _, f in scores]))}"
        )
    print(f"Artikel, {art} (aus den gedruckten geschätzt): " + " | ".join(parts))


def main() -> None:
    run = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    notes = load_notes(Path(sys.argv[2]))
    pools = fitting(notes)
    materials = run["materialien"]
    for art in ("klar", "unscharf"):
        group = [m for m in materials if m["art"] == art]
        print(f"\n== {art}: {len(group)} Materialien")
        report(group, pools)
        combination(group, pools, art)
    print()
    without_topic(materials)
    print()
    separation(materials, notes)
    linking(materials, notes)
    print("\nLaufzeit:")
    for key, value in run["laufzeit"].items():
        print(f"  {key}: {value}")


main()
