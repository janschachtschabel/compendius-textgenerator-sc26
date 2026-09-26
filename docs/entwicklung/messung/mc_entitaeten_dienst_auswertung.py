"""M36 in the service evaluated (D62): precision, recall and F1 of each profile of /api/v2/entities, with M36's grades.

An article counts as right with grade 2; recall counts against the articles graded 2 in the pool of M36 for the same
text, so the numbers stand next to M36's. An article outside that pool has no grade: it counts as 0 and is listed.
Each variant is also compared with the way of M36 it stands for - llm-free the rules, balanced and best-quality "LLM
nennt", the check "LLM nennt, das LLM prüft (behält Note 2)" - text by text.

Usage (from the project folder):
python mc_entitaeten_dienst_auswertung.py <dienst.json> <m36 run.json> <grades.yaml> [<second grades.yaml>]
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

PROFILES = ("llm-free", "balanced", "best-quality", "mit Prüfung")


def grades_of(path: Path) -> dict[tuple[str, str], int]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {(entry["node_id"], entry["artikel"]): int(entry["note"]) for entry in data["noten"]}


def m36_way(row: dict[str, Any], profile: str) -> list[str]:
    """The articles of the M36 way a profile stands for."""
    ways = row["wege"]
    if profile == "llm-free":
        return list(ways["regeln"]["artikel"])
    named = list(ways["extract"]["artikel"])
    if profile in ("balanced", "best-quality"):
        return named
    return [title for title in named if ways["pruefung"]["noten"].get(title) == 2]


def scores(
    service: dict[str, dict[str, Any]], m36: dict[str, dict[str, Any]], grades: dict[tuple[str, str], int]
) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for node_id, row in service.items():
        right = {title for title in m36[node_id]["pool"] if grades.get((node_id, title)) == 2}
        for profile in PROFILES:
            found = row["profile"][profile].get("artikel", [])
            cell = table.setdefault(profile, {"gefunden": 0, "richtig": 0, "passend": 0, "note0": 0, "ohne": []})
            cell["gefunden"] += len(found)
            cell["richtig"] += sum(1 for title in found if title in right)
            cell["note0"] += sum(1 for title in found if grades.get((node_id, title)) == 0)
            cell["ohne"] += [title for title in found if (node_id, title) not in grades]
            cell["passend"] += len(right)
    for cell in table.values():
        p = cell["richtig"] / cell["gefunden"] if cell["gefunden"] else 0.0
        r = cell["richtig"] / cell["passend"] if cell["passend"] else 0.0
        cell.update(p=p, r=r, f1=2 * p * r / (p + r) if p + r else 0.0)
    return table


service = {row["node_id"]: row for row in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["materialien"]}
m36 = {
    row["node_id"]: row
    for row in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["materialien"]
    if "wege" in row
}
service = {node_id: row for node_id, row in service.items() if node_id in m36}
tables = [scores(service, m36, grades_of(Path(path))) for path in sys.argv[3:5]]
failed = [(node_id, p) for node_id, row in service.items() for p in PROFILES if "artikel" not in row["profile"][p]]
print(f"{len(service)} Materialtexte; ohne Antwort 200: {failed}")
print(f"\n{'Profil':14s} {'Artikel':>8s} {'P':>11s} {'R':>11s} {'F1':>11s} {'Note 0':>7s}  ohne Note")
for profile in PROFILES:
    cells = [table[profile] for table in tables]

    def both(key: str, cells: list[dict[str, Any]] = cells) -> str:
        values = [f"{cell[key]:.2f}" for cell in cells]
        return values[0] + (f" ({values[1]})" if len(values) > 1 else "")

    first = cells[0]
    print(
        f"{profile:14s} {first['gefunden']:8d} {both('p'):>11s} {both('r'):>11s} {both('f1'):>11s} "
        f"{first['note0']:7d}  {len(first['ohne'])} {first['ohne'][:6]}"
    )

print("\nGleich wie der Weg von M36, Text für Text (Artikelmengen):")
for profile in PROFILES:
    same = [
        node_id
        for node_id, row in service.items()
        if set(row["profile"][profile].get("artikel", [])) == set(m36_way(m36[node_id], profile))
    ]
    print(f"  {profile:14s} {len(same)} von {len(service)}")
    for node_id, row in service.items():
        if node_id not in same:
            ours, theirs = set(row["profile"][profile].get("artikel", [])), set(m36_way(m36[node_id], profile))
            print(f"    {node_id[:8]}: nur im Dienst {sorted(ours - theirs)}, nur in M36 {sorted(theirs - ours)}")

named = [row["profile"]["balanced"] for row in service.values() if row["profile"]["balanced"].get("llm")]
checked = [row["profile"]["mit Prüfung"] for row in service.values() if row["profile"]["mit Prüfung"].get("llm")]
check_tokens = [
    row["profile"]["mit Prüfung"]["llm"]["total_tokens"] - row["profile"]["balanced"]["llm"]["total_tokens"]
    for row in service.values()
    if row["profile"]["mit Prüfung"].get("llm") and row["profile"]["balanced"].get("llm")
]
print(
    f"\nTokens im Median: balanced {statistics.median(r['llm']['total_tokens'] for r in named):.0f}, "
    f"mit Prüfung {statistics.median(r['llm']['total_tokens'] for r in checked):.0f}, davon die Prüfung "
    f"{statistics.median(check_tokens):.0f} (im Median {statistics.median(r['llm']['checked'] for r in checked):.0f} "
    f"Artikel); Sekunden im Median (mit HTTP): llm-free "
    f"{statistics.median(r['profile']['llm-free']['sekunden'] for r in service.values()):.2f}, balanced "
    f"{statistics.median(r['sekunden'] for r in named):.2f}, mit Prüfung "
    f"{statistics.median(r['sekunden'] for r in checked):.2f}"
)
fallbacks = [(node_id, p, row["profile"][p]["llm"]["fallback"]) for node_id, row in service.items() for p in PROFILES
             if (row["profile"][p].get("llm") or {}).get("fallback")]  # fmt: skip
print(f"Rückfälle: {fallbacks}")
