"""M48: the blind gradings of mc_profilvergleich_boegen.py merged with the key, per kind of topic and profile, and
the figures of the runs of mc_kompendium_profil.py beside them. Writes the result without the texts and without the
quotes of the errors.

Usage: python mc_profilvergleich_auswertung.py <runs.json> <schluessel.json> <out.json> <rater.json> [<rater.json> ...]
  [--variants=a,b,c] [--note=...]: the variants of the sheets (default the five profiles of M48) and the note of the result
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from mc_profilvergleich_boegen import KINDS, PROFILES

SCORES = ("passung", "nutzen", "vollstaendigkeit", "lesbarkeit")
KIND_OF = {topic: kind for kind, topics in KINDS.items() for topic in topics}
GROUPS = (*KINDS, "alle")


def grades(key: dict, raters: list[dict], variants: tuple[str, ...] = PROFILES) -> dict[str, dict[str, dict[str, float]]]:
    """Mean of every score of both raters, per kind of topic and profile, and over all topics."""
    collected: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for topic, letters in key.items():
        for letter, profile in letters.items():
            for rater in raters:
                grade = rater[topic][letter]
                errors = grade.get("fehler", [])
                for group in (KIND_OF[topic], "alle"):
                    values = collected[(group, profile)]
                    for score in SCORES:
                        values[score].append(grade[score])
                    values["schwere_fehler"].append(sum(1 for e in errors if e.get("schwere") == "schwer"))
                    values["leichte_fehler"].append(sum(1 for e in errors if e.get("schwere") != "schwer"))
    table: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for (group, profile), values in collected.items():
        table[group][profile] = {name: round(mean(found), 2) for name, found in values.items()}
    return {group: {profile: table[group][profile] for profile in variants if profile in table[group]} for group in GROUPS}


def agreement(key: dict, raters: list[dict]) -> dict[str, dict[str, int]]:
    """How far the first two raters lay apart, per score."""
    first, second = raters[:2]
    found = {}
    for score in SCORES:
        gaps = [abs(first[t][x][score] - second[t][x][score]) for t, letters in key.items() for x in letters]
        found[score] = {
            "same": sum(g == 0 for g in gaps),
            "one_apart": sum(g == 1 for g in gaps),
            "two_or_more": sum(g >= 2 for g in gaps),
            "pairs": len(gaps),
        }
    return found


def share(run: dict) -> float:
    return run["model_chars"] / run["chars"] if run["chars"] else 0.0


def runs_table(runs: list[dict], variants: tuple[str, ...] = PROFILES) -> dict[str, dict[str, dict]]:
    """Median and span of the figures of the runs, per kind of topic and profile, and over all topics."""
    table: dict[str, dict[str, dict]] = defaultdict(dict)
    for group in GROUPS:
        for profile in variants:
            own = [r for r in runs if r["variant"] == profile and group in ("alle", KIND_OF[r["topic"]])]
            if not own:
                continue
            tokens = [r.get("tokens") or {} for r in own]
            totals = [t.get("total", 0) for t in tokens]
            table[group][profile] = {
                "runs": len(own),
                "seconds": median(r["s"] for r in own),
                "seconds_span": [min(r["s"] for r in own), max(r["s"] for r in own)],
                "tokens": median(totals),
                "tokens_span": [min(totals), max(totals)],
                "cached": median(t.get("cached", 0) for t in tokens),
                "chars": median(r["chars"] for r in own),
                "blocks": median(r["blocks"] for r in own),
                "llm_blocks": median(r["llm_blocks"] for r in own),
                "marked": median(r["marked"] for r in own),
                "model_share": round(median(share(r) for r in own), 3),
                "model_share_span": [round(min(share(r) for r in own), 3), round(max(share(r) for r in own), 3)],
                "cited": median(r["cited"] for r in own),
                "generation_fallbacks": sum(len(r.get("fallbacks") or []) for r in own),
                "heading_as_asked": sum(r["heading"] == r["topic"] for r in own),
            }
    return table


def run_rows(runs: list[dict]) -> list[dict]:
    """Every run without its text: what it chose, what it cost, what it wrote."""
    kept = ("topic", "variant", "s", "timings", "heading", "main", "method", "tokens", "blocks", "llm_blocks", "chars",
            "marked", "model_chars", "cited", "fallbacks", "matching_fallbacks", "note", "target_length", "prompts")
    return [{**{name: run.get(name) for name in kept}, "kind": KIND_OF[run["topic"]], "sources": run["sources"][:12]}
            for run in runs]


def without_quotes(rater: dict) -> dict:
    return {topic: {letter: {**grade, "fehler": [{k: v for k, v in e.items() if k != "zitat"} for e in grade["fehler"]]}
                    for letter, grade in letters.items()}
            for topic, letters in rater.items()}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    variants = tuple(options["variants"].split(",")) if "variants" in options else PROFILES
    every = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    runs = [r for r in every if "text" in r]
    key = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    raters = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args[3:]]
    result = {
        "kinds": {kind: list(topics) for kind, topics in KINDS.items()},
        "grades": grades(key, raters, variants),
        "agreement": agreement(key, raters),
        "runs": runs_table(runs, variants),
        "failed": [{"topic": r["topic"], "variant": r["variant"], "error": r["error"]} for r in every if "error" in r],
        "run_rows": run_rows(runs),
        "key": key,
        "raters": [without_quotes(rater) for rater in raters],
        "note": options.get(
            "note",
            "M48 (D70): five profiles, part 1, nine topics in three kinds, one run each with fresh answers of the "
            "b-api (B_API_RESPONSE_CACHE=false), two blind Claude raters; no texts, no quotes of the errors.",
        ),
    }
    Path(args[2]).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for group in GROUPS:
        print(f"== {group}")
        for profile in variants:
            g, r = result["grades"][group][profile], result["runs"][group].get(profile, {})
            print(f"  {profile:24s} passung {g['passung']:.2f} nutzen {g['nutzen']:.2f} vollst. "
                  f"{g['vollstaendigkeit']:.2f} lesb. {g['lesbarkeit']:.2f} schwer {g['schwere_fehler']:.2f} "
                  f"leicht {g['leichte_fehler']:.2f} | {r.get('seconds')} s {r.get('tokens')} Tokens "
                  f"{r.get('chars')} Zeichen KI-Anteil {r.get('model_share')}")


if __name__ == "__main__":
    main()
