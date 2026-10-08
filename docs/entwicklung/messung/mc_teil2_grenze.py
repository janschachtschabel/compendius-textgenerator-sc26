"""Messskript M81b (08.10.2026, Audit vom 18.09., D-03): die Treffergrenze der Lehrplansuche.

Die Suche von Teil 2 bewertet höchstens 20.000 Elemente (``DEFAULT_SEARCH_LIMIT``); darüber bleiben seit PE-05 die
stärksten Rollen, innerhalb einer Rolle entschied die Reihenfolge des Harvests. Drei Schritte:

1. ``treffer <themen.json> <out.json> [<basis-url>]`` aus der venv dieses Projekts gegen den laufenden Dienst: je Thema
   ein Kompendium ``llm-free`` mit Teil 1 und 2, daraus die Suchwörter von Teil 2, ``total_hits``, ``cut_hits``, die
   gedruckten Elemente und ihre Länder.
2. ``suche <treffer.json>`` im Container mit dem Lehrplan-Cache, einmal mit dem Code des Images und einmal mit dem
   neuen Stand (``-v <repo>/app:/src/app:ro -e PYTHONPATH=/src`` im Einmal-Container): je Thema die Treffer der Suche mit
   den Wörtern aus Schritt 1 und ihre Zeit (beste von drei), je breitem Ein-Wort-Thema alle Treffer, die behaltenen je
   Land und die vertretenen Lehrpläne. Die Datei vorher in den Container kopieren, das Skript über stdin:

     docker cp treffer.json <container>:/tmp/treffer.json
     cat mc_teil2_grenze.py | docker exec -i -e PYTHONPATH=/app <container> python - suche /tmp/treffer.json > alt.json

3. ``vergleich <alt.json> <neu.json> <treffer.json> <out.json>`` stellt beides nebeneinander.

Ohne LLM; die Elemente selbst stehen nicht im Ergebnis (ob MEM-Daten weitergegeben werden dürfen, ist offen).
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

BROAD = [
    "Deutschland", "Sprache", "Kunst", "Musik", "Wasser", "Energie", "Mensch", "Natur", "Geschichte", "Gesellschaft",
    "Religion", "Kultur", "Leben", "Arbeit", "Bewegung", "Text", "Zahl", "Welt", "Zeit", "Raum", "Körper", "Umwelt",
    "Technik", "Medien", "Gesundheit", "ein", "und",
]


def hits_per_topic(topics_file: str, out_file: str, base: str = "http://127.0.0.1:8001") -> None:
    import httpx

    topics: list[str] = json.loads(Path(topics_file).read_text(encoding="utf-8"))
    rows: dict[str, Any] = {}
    with httpx.Client(base_url=base, timeout=900.0) as client:
        for topic in topics:
            body = json.dumps({"topic": topic, "preset": "llm-free", "parts": ["world", "curricula"]})
            response = client.post("/api/v2/compendium", content=body, headers={"Content-Type": "application/json"})
            if response.status_code != 200:
                rows[topic] = {"status": response.status_code}
                continue
            curricula = response.json().get("curricula") or {}
            summary = curricula.get("summary") or {}
            rows[topic] = {
                "keywords": curricula.get("keywords"),
                "total_hits": summary.get("total_hits"),
                "cut_hits": summary.get("cut_hits"),
                "matches": summary.get("matches"),
                "by_land": {land: sum(counts.values()) for land, counts in (summary.get("by_land") or {}).items()},
            }
    Path(out_file).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def search(hits_file: str) -> None:
    from app.sources.lehrplan.matcher import ROLE_ORDER
    from app.sources.lehrplan.store import DEFAULT_SEARCH_LIMIT, LehrplanStore

    store = LehrplanStore("/data/state/lehrplan.db")
    topics = json.loads(Path(hits_file).read_text(encoding="utf-8"))
    out: dict[str, Any] = {"themen": {}, "breit": {}}
    for topic, row in topics.items():
        if not row.get("keywords"):
            continue
        times, hits = [], []
        for _ in range(3):
            started = time.perf_counter()
            hits = store.search(row["keywords"], limit=DEFAULT_SEARCH_LIMIT, role_order=ROLE_ORDER)
            times.append(time.perf_counter() - started)
        out["themen"][topic] = {"iris": [hit.iri for hit in hits], "sekunden": round(min(times), 3)}
    for word in BROAD:
        times, kept = [], []
        for _ in range(3):
            started = time.perf_counter()
            kept = store.search([word], limit=DEFAULT_SEARCH_LIMIT, role_order=ROLE_ORDER)
            times.append(time.perf_counter() - started)
        every = store.search([word], limit=10**7, role_order=ROLE_ORDER)
        by_state: dict[str, int] = {}
        for hit in kept:
            by_state[hit.lehrplan.bundesland_code] = by_state.get(hit.lehrplan.bundesland_code, 0) + 1
        all_by_state: dict[str, int] = {}
        for hit in every:
            all_by_state[hit.lehrplan.bundesland_code] = all_by_state.get(hit.lehrplan.bundesland_code, 0) + 1
        out["breit"][word] = {
            "treffer": len(every),
            "behalten_je_land": by_state,
            "alle_je_land": all_by_state,
            "lehrplaene_behalten": len({hit.lehrplan.iri for hit in kept}),
            "lehrplaene_alle": len({hit.lehrplan.iri for hit in every}),
            "iris": [hit.iri for hit in kept],
            "sekunden": round(min(times), 3),
        }
    print(json.dumps(out, ensure_ascii=False))


def compare(old_file: str, new_file: str, hits_file: str, out_file: str) -> None:
    old, new = (json.loads(Path(name).read_text(encoding="utf-8")) for name in (old_file, new_file))
    topics = json.loads(Path(hits_file).read_text(encoding="utf-8"))
    totals = [row["total_hits"] for row in topics.values() if row.get("total_hits") is not None]
    result = {
        "themen": len(topics),
        "treffer_median": statistics.median(totals),
        "treffer_max": max(totals),
        "themen_gekuerzt": [topic for topic, row in topics.items() if row.get("cut_hits")],
        "themen_gleiche_treffer": sum(old["themen"][t]["iris"] == new["themen"][t]["iris"] for t in old["themen"]),
        "themen_sekunden": {
            "alt": round(sum(row["sekunden"] for row in old["themen"].values()), 3),
            "neu": round(sum(row["sekunden"] for row in new["themen"].values()), 3),
        },
        "breit": {
            word: {
                "treffer": old["breit"][word]["treffer"],
                "alle_je_land": old["breit"][word]["alle_je_land"],
                "alt": {key: old["breit"][word][key] for key in ("behalten_je_land", "lehrplaene_behalten", "sekunden")},
                "neu": {key: new["breit"][word][key] for key in ("behalten_je_land", "lehrplaene_behalten", "sekunden")},
                "lehrplaene_alle": old["breit"][word]["lehrplaene_alle"],
                "gleich": old["breit"][word]["iris"] == new["breit"][word]["iris"],
            }
            for word in old["breit"]
        },
    }
    Path(out_file).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    {"treffer": hits_per_topic, "suche": search, "vergleich": compare}[sys.argv[1]](*sys.argv[2:])
