"""Auswertung M57/M58 gepoolt (03.10.2026): Teil 2 je Profil und Weg, aus allen benoteten Elementen beider Messungen.

Je Lauf zog die Stichprobe bis zu sechs einzeln gezeigte und zwei gebündelte Elemente. Ein Element, das mehrere Läufe
eines Themas zeigen, hatte eine höhere Chance, gezogen zu werden; gepoolt zählt jedes gezogene und benotete Element
für jeden Weg, der es einzeln zeigt, mit dem Gewicht 1 / Chance (Hajek-Schätzer je Thema). Die Themen gehen wie in den
Stichproben mit min(6, gezeigt) ein; die Intervalle ziehen die Themen 2.000-mal neu (Saat 5758). Nur Gutachter 1:
Gutachter 2 sah in M58 nur 30 % der Paare.

  python mc_lehrplan_gepoolt.py bauen <m57_out.txt> <m58_out.txt> ergebnisse/m57_m58_gepoolt.json
  python mc_lehrplan_gepoolt.py auswerten ergebnisse/m57_m58_gepoolt.json

``bauen`` liest die Rohausgaben von mc_lehrplan_profile.py (M57) und mc_lehrplan_suchbegriffe.py (M58) mit allen
Elementen je Lauf (zu groß fürs Repository) und die Noten aus m57_lehrplan_profile.json und
m58_lehrplan_suchbegriffe.json; ``auswerten`` braucht nur die gebaute Datei.
"""

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent / "ergebnisse"
KINDS = ("einfach", "gruppe", "aspekt")
VARIANTS = (
    "llm-free/heute",
    "balanced/heute",
    "balanced/titel_und_begriffe",
    "balanced/mit_fach",
    "best-quality/heute",
    "best-quality/heute, nur LLM-2",
    "best-quality/mit_fach",
    "best-quality/mit_fach, nur LLM-2",
)
COMPARE = (
    ("llm-free/heute", "balanced/heute"),
    ("balanced/heute", "best-quality/heute"),
    ("best-quality/heute", "best-quality/heute, nur LLM-2"),
    ("balanced/heute", "balanced/mit_fach"),
    ("best-quality/heute, nur LLM-2", "best-quality/mit_fach, nur LLM-2"),
)


def _bundled(entry):
    return entry.get("matched_in") == "parent" and entry.get("note") != 2


def _runs(path, key=None):
    data = json.loads(Path(path).read_text(encoding="utf-8").split("JSON-START\n", 1)[1])
    return data[key] if key else data


def build(m57_out, m58_out, target):
    pools = []  # (topic, kind, variant, shown, bundled, sampled)
    for r in _runs(m57_out):
        if "error" in r:
            continue
        entries = r["entries"]
        shown = {e["iri"] for e in entries if not _bundled(e)}
        pools.append((r["topic"], r["kind"], f"{r['preset']}/heute", shown, {e["iri"] for e in entries if _bundled(e)}, True))
        if r["preset"] == "best-quality":
            two = {e["iri"] for e in entries if e.get("note") == 2}
            pools.append((r["topic"], r["kind"], "best-quality/heute, nur LLM-2", two, set(), False))
    for r in _runs(m58_out, "b"):
        if r.get("error"):
            continue
        for variant in ("titel_und_begriffe", "mit_fach"):
            if variant in r:
                entries = r[variant]["entries"]
                pools.append((r["topic"], r["kind"], f"{r['preset']}/{variant}", {e["iri"] for e in entries if not _bundled(e)},
                              {e["iri"] for e in entries if _bundled(e)}, True))
        if r["preset"] == "best-quality" and "mit_fach" in r:
            two = {e["iri"] for e in r["mit_fach"]["entries"] if e.get("note") == 2}
            pools.append((r["topic"], r["kind"], "best-quality/mit_fach, nur LLM-2", two, set(), False))
    miss = defaultdict(lambda: 1.0)
    for topic, _, _, shown, bundled, sampled in pools:
        if sampled:
            for pool, k in ((shown, 6), (bundled, 2)):
                for iri in pool:
                    miss[(topic, iri)] *= 1 - min(1.0, k / len(pool))
    grades = {}
    for name, rows in (("m57_lehrplan_profile.json", "stichprobe"), ("m58_lehrplan_suchbegriffe.json", "b_stichprobe")):
        for row in json.loads((HERE / name).read_text(encoding="utf-8"))[rows]:
            if row.get("note") is not None:
                grades[(row["thema"], row["iri"])] = row["note"]
    shows = defaultdict(list)
    for topic, _, variant, shown, _, _ in pools:
        for iri in shown:
            if (topic, iri) in grades:
                shows[(topic, iri)].append(VARIANTS.index(variant))
    out = {
        "note": "M57/M58 gepoolt (03.10.2026): je gezogenem und benotetem Paar die Note von Gutachter 1, die Chance, gezogen "
        "zu werden (pi), und die Wege, die es einzeln zeigen (Index in varianten); je Weg und Thema die Zahl der einzeln "
        "gezeigten Elemente. Auswertung: mc_lehrplan_gepoolt.py auswerten.",
        "varianten": list(VARIANTS),
        "art": {topic: kind for topic, kind, *_ in pools},
        "gezeigt": {v: {topic: len(shown) for topic, _, variant, shown, _, _ in pools if variant == v} for v in VARIANTS},
        "paare": [
            {"thema": t, "iri": i, "note": g, "pi": round(1 - miss[(t, i)], 6), "einzeln_in": sorted(set(shows[(t, i)]))}
            for (t, i), g in sorted(grades.items())
        ],
    }
    Path(target).write_text(json.dumps(out, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"{len(out['paare'])} Paare, {len(out['art'])} Themen")


def evaluate(source):
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    names, kind_of, shown = data["varianten"], data["art"], data["gezeigt"]
    per = defaultdict(lambda: defaultdict(list))  # variant -> topic -> [(note, weight)]
    for pair in data["paare"]:
        for index in pair["einzeln_in"]:
            per[names[index]][pair["thema"]].append((pair["note"], 1 / pair["pi"]))

    def topic_shares(variant, topic):
        rows = per[variant].get(topic)
        if not rows:
            return None
        total = sum(w for _, w in rows)
        return sum(w for g, w in rows if g == 2) / total, sum(w for g, w in rows if g == 0) / total

    def estimate(variant, topics):
        weight = fit = unfit = 0.0
        for topic in topics:
            shares = topic_shares(variant, topic) if shown[variant].get(topic) else None
            if shares is not None:
                w = min(6, shown[variant][topic])
                weight, fit, unfit = weight + w, fit + w * shares[0], unfit + w * shares[1]
        return (fit / weight, unfit / weight) if weight else (0.0, 0.0)

    rng = random.Random(5758)
    for kind in KINDS:
        topics = sorted(t for t, k in kind_of.items() if k == kind)
        draws = [[rng.choice(topics) for _ in topics] for _ in range(2000)]
        print(f"-- {kind} ({len(topics)} Themen): passend / unpassend [95 %-Intervall passend], Themen mit passendem Element")
        for variant in names:
            fit, unfit = estimate(variant, topics)
            spread = sorted(estimate(variant, d)[0] for d in draws)
            seen = sum(1 for t in topics if any(g == 2 for g, _ in per[variant].get(t, [])))
            print(f"   {variant:34} {fit:4.0%} / {unfit:4.0%}  [{spread[50]:4.0%}, {spread[1949]:4.0%}]  {seen:2}")
        for a, b in COMPARE:
            diffs = sorted(estimate(b, d)[0] - estimate(a, d)[0] for d in draws)
            print(f"   {b} gegen {a}: {estimate(b, topics)[0] - estimate(a, topics)[0]:+.0%} [{diffs[50]:+.0%}, {diffs[1949]:+.0%}]")
        # passende Elemente von best-quality/heute, die nur LLM-2 in die Bündelzeile schöbe
        moved = total = 0.0
        two = names.index("best-quality/heute, nur LLM-2")
        for pair in data["paare"]:
            if kind_of[pair["thema"]] == kind and pair["note"] == 2 and names.index("best-quality/heute") in pair["einzeln_in"]:
                total += 1 / pair["pi"]
                moved += (two not in pair["einzeln_in"]) / pair["pi"]
        print(f"   nur LLM-2 schöbe {moved / total:.0%} der passenden Elemente von best-quality/heute in die Bündelzeile")


if __name__ == "__main__":
    if sys.argv[1] == "bauen":
        build(*sys.argv[2:5])
    else:
        evaluate(sys.argv[2])
