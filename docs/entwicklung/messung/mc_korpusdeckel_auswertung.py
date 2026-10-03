"""Auswertung M69 (04.10.2026): was der Korpusdeckel je Thema abschnitt und wem.

Liest die Ausgabe von mc_korpusdeckel.py (JSON nach JSON-START) und ordnet jedes Thema ein: Deckel nicht erreicht,
erreicht ohne leer ausgegangene Nebenquelle, erreicht mit Nebenquellen ohne Absatz, oder schon Hauptartikel und
Artikel desselben Themas über dem Deckel. Dazu die Themen mit den meisten Absätzen im Hauptartikel.

Usage: python mc_korpusdeckel_auswertung.py <lauf.txt>
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# as app/compendium/corpus.py ORIGIN_PRIORITY; anything else ranks last
PRIORITY = {"primary": 0, "same_topic": 1, "material": 2, "node": 2, "named": 3, "linked": 3, "search": 4}


def per_source(row: dict) -> list[dict]:
    """Every source with its rank, its paragraphs before the cap and what it kept, in the order the cap filled."""
    by_rank: dict[int, list[int]] = {}
    for index, origin in enumerate(row["origins"]):
        by_rank.setdefault(PRIORITY.get(origin, len(PRIORITY)), []).append(index)
    sources = []
    for rank, call in zip(sorted(by_rank), row["ranks"], strict=True):
        for index, need, allowed in zip(by_rank[rank], call["needs"], call["allowed"], strict=True):
            sources.append({"rank": rank, "title": row["titles"][index], "origin": row["origins"][index],
                            "need": need, "allowed": allowed})
    return sources


def main() -> None:
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    rows = json.loads(text.split("JSON-START\n", 1)[1])
    done = [r for r in rows if "error" not in r]
    cap = done[0]["max_chunks"]
    kinds = {"nicht erreicht": [], "erreicht, jede Nebenquelle mit Absätzen": [], "Nebenquelle leer": [],
             "Hauptartikel und Zwilling über dem Deckel": []}
    for row in done:
        sources = per_source(row)
        top = sum(s["need"] for s in sources if s["rank"] <= 1)
        side = [s for s in sources if s["rank"] >= 2 and s["need"] > 0]
        row["top"], row["side_need"] = top, sum(s["need"] for s in side)
        row["side_empty"] = [s["title"] for s in side if s["allowed"] == 0]
        row["side_kept"] = sum(s["allowed"] for s in side)
        if top >= cap:
            kinds["Hauptartikel und Zwilling über dem Deckel"].append(row)
        elif row["side_empty"]:
            kinds["Nebenquelle leer"].append(row)
        elif row["truncated"]:
            kinds["erreicht, jede Nebenquelle mit Absätzen"].append(row)
        else:
            kinds["nicht erreicht"].append(row)
    print(f"{len(done)} Themen ({len(rows) - len(done)} ohne Artikel), Deckel {cap} Absätze")
    print(f"Absätze von Hauptartikel und Zwilling: Median {statistics.median(r['top'] for r in done)}, "
          f"Maximum {max(r['top'] for r in done)}")
    for name, members in kinds.items():
        print(f"- {name}: {len(members)}")
        for row in sorted(members, key=lambda r: -r["top"])[:8]:
            if name == "nicht erreicht":
                break
            print(f"    {row['topic']} -> {row['main']}: Haupt+Zwilling {row['top']}, Nebenquellen brauchten "
                  f"{row['side_need']}, bekamen {row['side_kept']}, leer: {len(row['side_empty'])} "
                  f"{row['side_empty'][:3]}")


if __name__ == "__main__":
    main()
