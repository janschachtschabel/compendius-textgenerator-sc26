"""M86: blind sheets for the block budgets - per profile one sheet with every topic of the runs, the factors of
mc_kompendium_profil.py --budgets as texts A to D in a seeded random order per topic, cut as in M48 (blocks 1-4 and
8-10, without citation numbers and model knowledge labels). Sheets, keys and the instructions of M48 for four texts
per topic go into one folder outside the repository.

Usage: python mc_budget_boegen.py <folder> <runs.json> [<runs.json> ...] [--profiles=a,b] [--budgets=1,2,4,10]
  [--seed=86]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from mc_profilvergleich_boegen import COUNT_WORDS, KINDS, LETTERS, NO_TEXT, excerpt, instructions

PROFILES = ("llm-free", "balanced", "best-quality-generated")
BUDGETS = (1, 2, 4, 10)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    profiles = tuple(options["profiles"].split(",")) if "profiles" in options else PROFILES
    budgets = tuple(int(f) for f in options["budgets"].split(",")) if "budgets" in options else BUDGETS
    folder = Path(args[0])
    folder.mkdir(parents=True, exist_ok=True)
    runs = [run for path in args[1:] for run in json.loads(Path(path).read_text(encoding="utf-8"))]
    found = {(r["topic"], r["variant"]): r for r in runs if "text" in r}
    measured = {topic for topic, _ in found}
    topics = [topic for listed in KINDS.values() for topic in listed if topic in measured]
    rng = random.Random(int(options.get("seed", 86)))
    for profile in profiles:
        variants = [f"{profile}@{factor}" for factor in budgets]
        key: dict[str, dict[str, str]] = {}
        parts: list[str] = []
        for topic in topics:
            order = list(variants)
            rng.shuffle(order)
            key[topic] = dict(zip(LETTERS[: len(order)], order, strict=True))
            parts.append(f"## Thema: {topic}\n")
            for letter, variant in key[topic].items():
                run = found.get((topic, variant), {})  # a run that failed wrote nothing: graded as such
                parts.append(f"### Text {letter}\n\n{excerpt(run['text']) if 'text' in run else NO_TEXT}\n")
        (folder / f"bogen_{profile}.md").write_text("\n".join(parts), encoding="utf-8")
        (folder / f"schluessel_{profile}.json").write_text(
            json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    words = instructions(len(budgets))
    assert "zu\ndrei Themen" in words, "the instructions of M48 changed"
    words = words.replace("zu\ndrei Themen", f"zu\n{COUNT_WORDS[len(topics)]} Themen")
    (folder / "anleitung.md").write_text(words, encoding="utf-8")
    print(f"{len(profiles)} Bögen, je {len(topics)} Themen mit {len(budgets)} Texten")


if __name__ == "__main__":
    main()
