"""M86: what the block budgets change - per profile and factor the time, the tokens and the text of the runs of
mc_kompendium_profil.py --budgets, the grades of the blind sheets of mc_budget_boegen.py beside them, and where the
shipped guards of a request would have stepped in. Writes the result without the texts and without the quotes of
the errors.

Usage: python mc_budget_auswertung.py <out.json> <runs.json> [<runs.json> ...] [--sheets=<folder>] [--gold=<gold.json>]
  [--profiles=a,b] [--budgets=1,2,4,10]
  The folder of the sheets holds schluessel_<profile>.json and one urteil_<profile>_<rater>.json per rater.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median

from mc_budget_boegen import BUDGETS, PROFILES
from mc_profilvergleich_auswertung import agreement, grades, without_quotes

# The guards of a request as shipped (app/settings.py): tokens per request, and the time of the provider openai
TOKEN_GUARD = {"llm-free": 60_000, "balanced": 60_000, "best-quality-generated": 180_000}
TIME_GUARD_S = 300


def share(run: dict) -> float:
    return run["model_chars"] / run["chars"] if run["chars"] else 0.0


def figures(own: list[dict], first: dict[str, dict]) -> dict:
    """Median and span of the runs of one variant; the growth against factor 1 as the median over the topics."""
    tokens = [r.get("tokens") or {} for r in own]
    totals = [t.get("total", 0) for t in tokens]
    timings = [r.get("timings") or {} for r in own]

    def growth(name: str) -> float | None:
        ratios = [r[name] / first[r["topic"]][name] for r in own if first.get(r["topic"], {}).get(name)]
        return round(median(ratios), 2) if ratios else None

    return {
        "runs": len(own),
        "seconds": round(median(r["s"] for r in own), 1),
        "seconds_span": [min(r["s"] for r in own), max(r["s"] for r in own)],
        "match_s": round(median(t.get("match", 0) for t in timings) / 1000, 1),
        "write_s": round(median(t.get("synthesize", 0) for t in timings) / 1000, 1),
        # The steps the budget acts on; with --fixed-corpus only the first run of a topic pays the corpus questions
        "steps_s": round(median(t.get("match", 0) + t.get("synthesize", 0) for t in timings) / 1000, 1),
        "resolve_s": round(median(t.get("resolve", 0) for t in timings) / 1000, 1),
        "tokens": median(totals),
        "tokens_span": [min(totals), max(totals)],
        "prompt_tokens": median(t.get("prompt", 0) for t in tokens),
        "completion_tokens": median(t.get("completion", 0) for t in tokens),
        "cached": median(t.get("cached", 0) for t in tokens),
        "calls": median(t.get("calls", 0) for t in tokens),
        "chars": median(r["chars"] for r in own),
        "chars_span": [min(r["chars"] for r in own), max(r["chars"] for r in own)],
        "chars_growth": growth("chars"),
        "evidence": median(r["evidence"] for r in own),
        "evidence_growth": growth("evidence"),
        "cited": median(r["cited"] for r in own),
        "blocks": median(r["blocks"] for r in own),
        "model_share": round(median(share(r) for r in own), 3),
        "model_share_span": [round(min(share(r) for r in own), 3), round(max(share(r) for r in own), 3)],
        "generation_fallbacks": sum(sum((r.get("fallbacks") or {}).values()) for r in own),
        "matching_fallbacks": sum(sum((r.get("matching_fallbacks") or {}).values()) for r in own),
    }


def guards(runs: list[dict]) -> list[dict]:
    """The runs a shipped guard would have cut: more tokens than the request's cap, or longer than its time."""
    found = []
    for run in runs:
        profile = run["variant"].split("@")[0]
        total = (run.get("tokens") or {}).get("total") or 0
        if total > TOKEN_GUARD.get(profile, 180_000) or run["s"] > TIME_GUARD_S:
            found.append({"topic": run["topic"], "variant": run["variant"], "tokens": total, "s": run["s"]})
    return found


def run_rows(runs: list[dict]) -> list[dict]:
    """Every run without its text: what it chose, what it cost, what it wrote."""
    kept = (
        "topic",
        "variant",
        "budget",
        "s",
        "timings",
        "main",
        "tokens",
        "blocks",
        "llm_blocks",
        "chars",
        "model_chars",
        "evidence",
        "cited",
        "fallbacks",
        "matching_fallbacks",
        "note",
    )
    return [{**{name: run.get(name) for name in kept}, "sources": run["sources"][:12]} for run in runs]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    profiles = tuple(options["profiles"].split(",")) if "profiles" in options else PROFILES
    budgets = tuple(int(f) for f in options["budgets"].split(",")) if "budgets" in options else BUDGETS
    every = [run for path in args[1:] for run in json.loads(Path(path).read_text(encoding="utf-8"))]
    runs = [r for r in every if "text" in r]
    result: dict = {"profiles": {}, "guards": guards(runs), "run_rows": run_rows(runs)}
    result["failed"] = [
        {"topic": r["topic"], "variant": r["variant"], "error": r["error"]} for r in every if "error" in r
    ]
    sheets = Path(options["sheets"]) if "sheets" in options else None
    for profile in profiles:
        variants = tuple(f"{profile}@{factor}" for factor in budgets)
        first = {r["topic"]: r for r in runs if r["variant"] == variants[0]}
        entry: dict = {
            "runs": {v: figures(own, first) for v in variants if (own := [r for r in runs if r["variant"] == v])}
        }
        if sheets is not None and (sheets / f"schluessel_{profile}.json").exists():
            key = json.loads((sheets / f"schluessel_{profile}.json").read_text(encoding="utf-8"))
            paths = sorted(sheets.glob(f"urteil_{profile}_*.json"))
            raters = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
            if raters:
                entry["grades"] = grades(key, raters, variants)["alle"]
                entry["agreement"] = agreement(key, raters) if len(raters) > 1 else None
                entry["raters"] = [without_quotes(rater) for rater in raters]
                entry["key"] = key
        result["profiles"][profile] = entry
    if "gold" in options:
        result["gold"] = json.loads(Path(options["gold"]).read_text(encoding="utf-8"))
    Path(args[0]).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for profile, entry in result["profiles"].items():
        print(f"== {profile}")
        for variant, f in entry["runs"].items():
            g = (entry.get("grades") or {}).get(variant, {})
            print(
                f"  {variant:28s} {f['seconds']:>5} s {f['tokens']:>7} Tokens {f['chars']:>6} Zeichen "
                f"(x{f['chars_growth']}) Belege {f['evidence']:>5} (x{f['evidence_growth']}) "
                f"KI {f['model_share']:.2f} | " + " ".join(f"{k[:5]} {v:.2f}" for k, v in g.items())
            )
    print("Schutzgrenzen:", result["guards"] or "keine")


if __name__ == "__main__":
    main()
