"""The citation markers of a written block, ``[1]``: the evidence numbers a sentence cites."""

from __future__ import annotations

import re

CITATION_MARKER_RE = re.compile(r"\[(\d{1,3})\]")


def marker_numbers(text: str) -> list[int]:
    """Evidence numbers in order of first appearance."""
    return list(dict.fromkeys(int(m) for m in CITATION_MARKER_RE.findall(text)))
