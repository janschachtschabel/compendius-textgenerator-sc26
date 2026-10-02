"""M52: the overview table of the five profiles - quality, time and cost - as Markdown, from the evaluation of
mc_profilvergleich_auswertung.py, so that page 09 and the decision paper print the measured numbers, not copies.

Usage: python mc_profiltabelle.py <m52_profiluebersicht.json>
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

PROFILES = ("llm-free", "balanced", "best-quality", "best-quality-generated", "best-coverage-generated")
MAIN_ARTICLE = {"llm-free": 87, "balanced": 91, "best-quality": 93, "best-quality-generated": 93,
                "best-coverage-generated": 93}  # M35 (with D63 unchanged, M39); D72 left the article choice alone


def de(value: float, places: str = "0.1") -> str:
    rounded = Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{rounded:,}".replace(",", "X").replace(".", ",").replace("X", ".")


def tokens(value: float) -> str:
    return "0" if not value else de(round(value, -2) if value >= 5_000 else round(value, -1), "1")


def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    grades, runs = data["grades"], data["runs"]

    def grade(kind: str, score: str) -> list[str]:
        values = [grades[kind][p][score] for p in PROFILES]
        best = max(values)
        return [f"**{de(v)}**" if v == best else de(v) for v in values]

    def run(render: Callable[[dict[str, Any]], str]) -> list[str]:
        return [render(runs["alle"][p]) for p in PROFILES]

    rows = [
        ("**Güte**, Noten von 1 bis 5", None),
        ("Passung, Thema mit eigenem Artikel", grade("einfach", "passung")),
        ("Passung, Sammelthema", grade("Sammelthema", "passung")),
        ("Passung, Thema mit Aspekt", grade("Aspekt", "passung")),
        ("Nutzen", grade("alle", "nutzen")),
        ("Vollständigkeit", grade("alle", "vollstaendigkeit")),
        ("Lesbarkeit", grade("alle", "lesbarkeit")),
        ("Fehler je Text, schwer und leicht",
         [f"{de(grades['alle'][p]['schwere_fehler'], '0.01')} und {de(grades['alle'][p]['leichte_fehler'], '0.01')}"
          for p in PROFILES]),
        ("Überschrift ist das angefragte Thema", run(lambda r: f"{r['heading_as_asked']} von {r['runs']}")),
        ("Hauptartikel richtig, 94 Goldanfragen (M35)", [f"{MAIN_ARTICLE[p]} von 94" for p in PROFILES]),
        ("**Zeit**", None),
        ("Teil 1, Median (Spanne)", run(lambda r: f"{de(r['seconds'])} s ({de(r['seconds_span'][0])} bis "
                                                  f"{de(r['seconds_span'][1])} s)")),
        ("**Kosten**", None),
        ("Tokens, Median", run(lambda r: tokens(r["tokens"]))),
        ("davon aus dem Prompt-Cache", run(lambda r: tokens(r["cached"]) if r["tokens"] else "–")),
        ("**Text**", None),
        ("Zeichen, Median", run(lambda r: de(r["chars"], "1"))),
        ("Bausteine mit Text, von 10", run(lambda r: de(r["blocks"], "1"))),
        ("Modellwissen am Text, Median", run(lambda r: f"{de(r['model_share'] * 100, '1')} %")),
    ]
    print("| | " + " | ".join(f"`{p}`" for p in PROFILES) + " |")
    print("|---|" + "---|" * len(PROFILES))
    for label, cells in rows:
        print(f"| {label} | " + " | ".join(cells or [""] * len(PROFILES)) + " |")


if __name__ == "__main__":
    main()
