"""The packages of app/ depend on each other one way only (audit 2026-09-18, A-01 and A-04).

Packages that import each other cannot be read, tested or changed apart: the knowledge took its words and its
heading lexicon from the matching while the matching built on the knowledge, the jobs ran the syncs of the sources
while the sources took their base and their lock from the jobs. And the sources wrote their Markdown with the helpers
of the synthesis. Below every part now: app/markup (escaping, facet and citation markers, formulas as text) and the
plain modules at the top of app/ (files, locks, wiring aside).
"""

from __future__ import annotations

import ast
import graphlib
from collections import defaultdict
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _package(module: str) -> str | None:
    """``app.sources.zim.active`` -> ``sources``; a module of app/ itself is its own package (``service``)."""
    parts = module.split(".")
    return parts[1] if parts[0] == "app" and len(parts) > 1 else None


def module_name(path: Path) -> str:
    """``app/sources/zim/active.py`` -> ``app.sources.zim.active``; a package by its ``__init__.py``."""
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported_modules(path: Path) -> list[str]:
    """What the module at ``path`` imports, anywhere in it: ``import a.b``, ``from a.b import c`` as a.b and a.b.c (c
    may be a module, as in ``from app import prose``), relative imports resolved against its package (review of
    2026-10-08: the forms beside the absolute ones went unseen)."""
    module = module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                base = ".".join([*anchor[: len(anchor) - (node.level - 1)], *([base] if base else [])])
            names += [base, *(f"{base}.{alias.name}" for alias in node.names)]
    return names


@cache
def package_edges() -> dict[tuple[str, str], frozenset[str]]:
    """Every import between two packages of app/, with the files that make it; typing imports count as well."""
    edges: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in sorted((ROOT / "app").rglob("*.py")):
        source = _package(module_name(path))
        for target in map(_package, imported_modules(path)):
            if source is not None and target is not None and target != source:
                edges[(source, target)].add(path.relative_to(ROOT).as_posix())
    return {pair: frozenset(files) for pair, files in edges.items()}


def test_no_two_packages_import_each_other() -> None:
    edges = package_edges()
    mutual = sorted({tuple(sorted(pair)) for pair in edges if (pair[1], pair[0]) in edges})

    assert not mutual, {f"{a} <-> {b}": (sorted(edges[(a, b)]), sorted(edges[(b, a)])) for a, b in mutual}


def test_the_packages_import_each_other_in_no_cycle() -> None:
    """A-01 is about cycles, of any length: three packages that import each other in a ring are as tied as two."""
    graph: dict[str, set[str]] = defaultdict(set)
    for source, target in package_edges():
        graph[source].add(target)

    graphlib.TopologicalSorter(graph).prepare()  # raises CycleError with the ring


def test_the_sources_write_their_markdown_without_the_synthesis() -> None:
    edges = package_edges()

    assert ("sources", "synthesis") not in edges and ("sources", "compose") not in edges


def test_the_markup_stands_below_every_part() -> None:
    edges = package_edges()

    assert sorted(target for source, target in edges if source == "markup") == []
