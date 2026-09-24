"""How far two raters agree on the notes 0, 1 and 2, shared by the evaluations that have a second rater (M22, M23)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Mapping
from typing import Any


def agreement(first: Mapping[Hashable, Mapping[str, Any]], second: Mapping[Hashable, Mapping[str, Any]]) -> None:
    """Print same notes, Cohen's kappa and the cross table of two raters who noted the same elements."""
    keys = sorted(first)
    assert keys == sorted(second), "the two files must note the same elements"
    pairs = [(first[key]["note"], second[key]["note"]) for key in keys]
    observed = sum(a == b for a, b in pairs) / len(pairs)
    first_counts, second_counts = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first_counts[note] * second_counts[note] for note in (0, 1, 2)) / len(pairs) ** 2
    kappa = (observed - expected) / (1 - expected)
    same_fit = sum((a == 2) == (b == 2) for a, b in pairs) / len(pairs)
    same_zero = sum((a == 0) == (b == 0) for a, b in pairs) / len(pairs)
    print(
        f"\nÜbereinstimmung auf {len(pairs)} Elementen: gleiche Note {observed * 100:.0f} % "
        f"(Cohens Kappa {kappa:.2f}), einig über passend {same_fit * 100:.0f} %, "
        f"einig über Note 0 {same_zero * 100:.0f} %"
    )
    print("Kreuztabelle (Zeile erste, Spalte zweite Note):")
    table = Counter(pairs)
    for a in (0, 1, 2):
        print(f"  {a}: " + "  ".join(f"{table[(a, b)]:3}" for b in (0, 1, 2)))
