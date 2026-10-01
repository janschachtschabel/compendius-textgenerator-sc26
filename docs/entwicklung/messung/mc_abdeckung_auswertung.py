"""M47: the blind gradings of mc_abdeckung_boegen.py merged with the key, topics with an aspect and controls apart,
and the figures of the runs beside them. Writes the result without the texts and without the quotes of the errors.

Usage: python mc_abdeckung_auswertung.py <runs.json> <schluessel.json> <out.json> <rater.json> [<rater.json> ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

CONTROLS = {"Photosynthese", "Französische Revolution"}
ORDER = ["bcg", "bcg-hl", "bqg"]
SCORES = ("passung", "nutzen", "vollstaendigkeit")
RUN_FIELDS = ("topic", "variant", "s", "timings", "heading", "main", "method", "tokens", "blocks", "llm_blocks", "chars",
              "marked", "cited", "fallbacks", "prompts")


def grades(key: dict, raters: list[dict]) -> dict[str, dict[str, dict[str, float]]]:
    collected: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for topic, letters in key.items():
        group = "Kontrolle" if topic in CONTROLS else "Aspekt"
        for letter, variant in letters.items():
            for rater in raters:
                grade = rater[topic][letter]
                for score in SCORES:
                    collected[(group, variant)][score].append(grade[score])
                errors = grade.get("fehler", [])
                collected[(group, variant)]["schwere_fehler"].append(sum(1 for e in errors if e.get("schwere") == "schwer"))
                collected[(group, variant)]["leichte_fehler"].append(sum(1 for e in errors if e.get("schwere") != "schwer"))
    table: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for (group, variant), values in collected.items():
        table[group][variant] = {name: round(mean(found), 2) for name, found in values.items()}
    return table


def runs_table(runs: list[dict]) -> dict[str, dict[str, float]]:
    table = {}
    for variant in ORDER:
        own = [r for r in runs if r["variant"] == variant]
        if own:
            table[variant] = {
                "seconds": median(r["s"] for r in own),
                "tokens": median(r["tokens"]["total"] for r in own),
                "cached": median(r["tokens"].get("cached", 0) for r in own),
                "chars": median(r["chars"] for r in own),
                "llm_blocks": median(r["llm_blocks"] for r in own),
                "cited": median(r["cited"] for r in own),
                "marked": median(r["marked"] for r in own),
            }
    return table


def main() -> None:
    runs = [r for r in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) if "text" in r]
    key = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    raters = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[4:]]
    agreement = [abs(raters[0][t][letter]["passung"] - raters[1][t][letter]["passung"]) for t in key for letter in key[t]]
    result = {
        "grades": grades(key, raters),
        "runs": runs_table(runs),
        "passung_agreement": {"same": agreement.count(0), "one_apart": agreement.count(1),
                              "two_or_more": sum(1 for d in agreement if d >= 2), "pairs": len(agreement)},
        "key": key,
        # the gradings without the quotes, which are sentences of the texts: the reason and the weight of each error stay
        "raters": [
            {
                topic: {
                    letter: {**grade, "fehler": [{k: v for k, v in e.items() if k != "zitat"} for e in grade.get("fehler", [])]}
                    for letter, grade in letters.items()
                }
                for topic, letters in rater.items()
            }
            for rater in raters
        ],
        "run_rows": [{name: r[name] for name in RUN_FIELDS if name in r} for r in runs],
    }
    Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({name: result[name] for name in ("grades", "runs", "passung_agreement")}, ensure_ascii=False,
                     indent=1))


if __name__ == "__main__":
    main()
