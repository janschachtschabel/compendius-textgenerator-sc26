"""The packages of app/ depend on each other one way only (audit 2026-09-18, A-01 and A-04).

Packages that import each other cannot be read, tested or changed apart: the knowledge took its words and its
heading lexicon from the matching while the matching built on the knowledge, the jobs ran the syncs of the sources
while the sources took their base and their lock from the jobs. And the sources wrote their Markdown with the helpers
of the synthesis. Below every part now: app/markup (escaping, facet and citation markers, formulas as text) and the
plain modules at the top of app/ (files, locks, wiring aside).
"""

from __future__ import annotations

import ast
from collections import defaultdict
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _package(module: str) -> str | None:
    """``app.sources.zim.active`` -> ``sources``; a module of app/ itself is its own package (``service``)."""
    parts = module.split(".")
    return parts[1] if parts[0] == "app" and len(parts) > 1 else None


@cache
def package_edges() -> dict[tuple[str, str], frozenset[str]]:
    """Every import between two packages of app/, with the files that make it; typing imports count as well."""
    edges: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in sorted((ROOT / "app").rglob("*.py")):
        source = _package(".".join(path.relative_to(ROOT).with_suffix("").parts))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                targets = [node.module]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                continue
            for target in map(_package, targets):
                if source is not None and target is not None and target != source:
                    edges[(source, target)].add(path.relative_to(ROOT).as_posix())
    return {pair: frozenset(files) for pair, files in edges.items()}


def test_the_sources_write_their_markdown_without_the_synthesis() -> None:
    edges = package_edges()

    assert ("sources", "synthesis") not in edges and ("sources", "compose") not in edges


def test_the_markup_stands_below_every_part() -> None:
    edges = package_edges()

    assert sorted(target for source, target in edges if source == "markup") == []
