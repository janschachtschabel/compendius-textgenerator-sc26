"""Harvest section headings from a Wikipedia ZIM (PLAN.md 4.4, stage 1).

Samples random articles, parses them with the production HTML parser and counts H2/H3 headings.
The output lists the most frequent headings with the slot the current lexicon assigns (or
``-`` when uncovered), so the uncovered frequent ones can be mapped by hand.

    uv run python scripts/harvest_headings.py --zim data/wikipedia_de_all_nopic_2026-01.zim \
        --sample 20000 --top 1000 --out eval/headings_top.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.matching.lexicon import HeadingLexicon
from app.sources.zim.archive import ZimArchive

_NUMERIC = re.compile(r"^\d{3,4}(er)?( Jahre| bis \d{3,4})?$")


def harvest(archive: ZimArchive, sample: int, seed: int) -> tuple[Counter[tuple[str, int]], int]:
    """Count (heading, level) over ``sample`` random articles; returns counts and parsed articles."""
    random.seed(seed)
    counts: Counter[tuple[str, int]] = Counter()
    parsed = 0
    attempts = 0
    started = time.perf_counter()
    while parsed < sample and attempts < sample * 4:
        attempts += 1
        try:
            entry = archive._archive.get_random_entry()
            if entry.is_redirect:
                continue
            item = entry.get_item()
            if not str(item.mimetype).startswith("text/html"):
                continue
            title = str(entry.title)
            if not title or ":" in title.split(" ")[0]:  # skip namespace pages such as "Wikipedia:..."
                continue
            article = archive.read(str(entry.path))
            if article is None:
                continue
            sections = archive.parse(article).sections
        except Exception as exc:  # a broken entry must not stop the harvest
            print(f"skip: {exc}", file=sys.stderr)
            continue
        parsed += 1
        for section in sections:
            if section.level in (2, 3) and section.heading:
                heading = re.sub(r"\s+", " ", section.heading).strip(" :")
                if heading and not _NUMERIC.match(heading):
                    counts[(heading, section.level)] += 1
        if parsed % 2000 == 0:
            elapsed = time.perf_counter() - started
            print(f"{parsed} Artikel in {elapsed:.0f} s ({attempts} Versuche)", file=sys.stderr)
    return counts, parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zim", required=True)
    parser.add_argument("--lexicon", default="config/heading_lexicon.yaml")
    parser.add_argument("--sample", type=int, default=20_000)
    parser.add_argument("--top", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=26)
    parser.add_argument("--out", default="eval/headings_top.csv")
    args = parser.parse_args()

    archive = ZimArchive(Path(args.zim))
    lexicon = HeadingLexicon.load(Path(args.lexicon))
    counts, parsed = harvest(archive, args.sample, args.seed)

    by_heading: Counter[str] = Counter()
    levels: dict[str, Counter[int]] = {}
    for (heading, level), count in counts.items():
        by_heading[heading] += count
        levels.setdefault(heading, Counter())[level] += count

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    covered = 0
    covered_occurrences = 0
    total_occurrences = sum(by_heading.values())
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["rank", "heading", "count", "share_percent", "h2", "h3", "lexicon_slot", "excluded"])
        for rank, (heading, count) in enumerate(by_heading.most_common(args.top), start=1):
            slot = lexicon.classify([heading]) or "-"
            excluded = lexicon.is_excluded([heading]) or lexicon.is_relation([heading])
            if slot != "-" or excluded:
                covered += 1
                covered_occurrences += count
            writer.writerow(
                [
                    rank,
                    heading,
                    count,
                    f"{100 * count / max(total_occurrences, 1):.2f}",
                    levels[heading][2],
                    levels[heading][3],
                    slot,
                    "ja" if excluded else "",
                ]
            )
    top_total = sum(count for _, count in by_heading.most_common(args.top))
    print(
        f"{parsed} Artikel, {total_occurrences} Überschriften, {len(by_heading)} verschiedene; "
        f"Top {args.top} decken {100 * top_total / max(total_occurrences, 1):.1f} % ab; "
        f"davon vom Lexikon erfasst: {covered} Überschriften = "
        f"{100 * covered_occurrences / max(total_occurrences, 1):.1f} % aller Vorkommen -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
