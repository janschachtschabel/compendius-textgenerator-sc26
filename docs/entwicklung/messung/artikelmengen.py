"""Precision, recall and F1 of the articles a compendium printed against the fitting ones, shared by M23 and M24."""

from __future__ import annotations


def f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def set_scores(titles: set[str], fitting: set[str]) -> tuple[float | None, float, float]:
    """Precision (None without a printed article), recall and F1 of the printed articles against the fitting ones,
    which must not be empty."""
    if not titles:
        return None, 0.0, 0.0
    hits = len(titles & fitting)
    precision, recall = hits / len(titles), hits / len(fitting)
    return precision, recall, f1(precision, recall)
