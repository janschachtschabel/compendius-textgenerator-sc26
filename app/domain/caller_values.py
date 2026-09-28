"""How a message repeats what a caller sent: a few values, each cut (audit 2026-09-28, SE-15 and AP-02).

Error answers that named every unknown field, archive or block grew with the request: 1.3 million unknown fields in
13 MB came back as a 422 of 114 MB after 19 s, and an archive name of 5 million characters as a 404 of 5 MB.
"""

from __future__ import annotations

from collections.abc import Sequence

NAMED = 3  # values a message names; the rest it counts
WIDTH = 60  # characters kept of each value


def cut(value: str, width: int = WIDTH) -> str:
    """``value`` up to ``width`` characters; a longer one ends in an ellipsis."""
    return value if len(value) <= width else value[: width - 1] + "…"


def listed(values: Sequence[str]) -> str:
    """The first three values, cut, and how many more there are: ``a, b, c und 17 weitere``."""
    shown = ", ".join(cut(value) for value in values[:NAMED])
    rest = len(values) - NAMED
    return f"{shown} und {rest} weitere" if rest > 0 else shown
