"""The topic of a collection whose title says nothing without its place in the topic tree (M71).

Jan, 2026-10-08: within a topic tree a collection is often named "Grundlagen" or alike; its context - the collections
above and below it - may tell what it is about, but it must stay selective and bring in nothing that rather belongs to
other collections of the tree. Measured on 32 collections of the staging repository (M71):

- with an LLM, the question N (D63) heard the title with the path above it, its own sub-collections, the titles of its
  first materials and its neighbours as not meant: its choice rose from 1.9 to 3.5-4.0 of 5 for neutral titles and
  from 2.8 to 3.9-4.3 for titles that name their subject matter (``describe``);
- without one, the title of the collection above beat the neutral title, 1.5-1.6 to 1.2 of 5, but harmed titles that
  name their subject matter, 1.9-2.0 to 2.6-2.7: the rules take it for a neutral title only (``nearest_informative``).

A format of material ("Experimente", "Übungen und Spiele") is no neutral title: its own article fitted better than
the collection above (M71).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from app.knowledge.topic import normalize_topic
from app.sources.wlo.tree import TreeContext

# Words that name a stage or a part of a topic, never its subject matter (the search words of M71 less the formats
# of material, whose own article fitted better)
NEUTRAL_WORDS = frozenset(
    {
        "allgemeines",
        "anfangsunterricht",
        "anwendungen",
        "basiswissen",
        "einführung",
        "einstieg",
        "grundbegriffe",
        "grundlage",
        "grundlagen",
        "hintergrund",
        "methoden",
        "sonstiges",
        "theorie",
        "vertiefung",
        "wiederholung",
        "überblick",
    }
)
_JOINING = frozenset({"und", "oder"})
_BRACKETED = re.compile(r"\([^()]*\)")
_WORD = re.compile(r"[^\W\d_]+")
MAX_TITLE = 120  # characters of one title the model hears


def clean_title(title: str) -> str:
    """The title without its additions in brackets ("Nachhaltigkeit (LTP)", "(Unsichtbar) Mediendidaktik")."""
    return " ".join(_BRACKETED.sub(" ", title).split()).strip(" -–/:")


def is_neutral(title: str) -> bool:
    """Whether the title names no subject matter: nothing but words of ``NEUTRAL_WORDS``, joined or numbered."""
    words = [word.casefold() for word in _WORD.findall(clean_title(title))]
    return any(word in NEUTRAL_WORDS for word in words) and all(
        word in NEUTRAL_WORDS or word in _JOINING for word in words
    )


def nearest_informative(tree: TreeContext) -> str | None:
    """The nearest collection above whose title names a subject matter, cleaned of its additions, or ``None``."""
    for title in reversed(tree.path):
        cleaned = clean_title(title)
        if cleaned and not is_neutral(cleaned):
            return cleaned
    return None


def stand_in(
    topic: str, tree: TreeContext | None, subjects: Sequence[str] = (), *, is_subject: Callable[[str], bool]
) -> str | None:
    """For a neutral ``topic``, what the rules resolve in its place: the nearest informative collection above it, else
    the first of ``subjects`` (labels), as a topic (``normalize_topic``, so "Physik: Optik" is "Optik"); ``None`` for
    a topic that names its subject matter, or without a tree."""
    if tree is None or not is_neutral(topic):
        return None
    above = nearest_informative(tree) or next(iter(subjects), None)
    return (normalize_topic(above, is_subject=is_subject).topic or above) if above else None


def shown_topic(title: str, stand_in: str | None) -> str:
    """The topic as a heading shows it: a neutral title with what stands in for it, "Grundlagen (Kernphysik)"; after a
    bracket of the title's own with a dash, "Grundlagen (erwachsene Lernende) – Ökologie"."""
    if not stand_in:
        return title
    return f"{title} – {stand_in}" if title.rstrip().endswith(")") else f"{title} ({stand_in})"


def tree_block(tree: TreeContext, stand_in: str | None) -> dict[str, Any]:
    """The place in the topic tree as the audit shows it: what was read, what the repository did not give, and what
    stood in for a neutral title."""
    return {
        "path": list(tree.path),
        "children": list(tree.children),
        "materials": list(tree.materials),
        "neighbours": list(tree.neighbours),
        "missing": list(tree.missing),
        "stand_in": stand_in,
    }


def describe(tree: TreeContext, subjects: Sequence[str] = ()) -> str:
    """The place of a collection as the question N hears it after the title (M71, variant N3): the path above it, its
    sub-collections and first materials, then its neighbours as not meant - for telling apart, never as content."""
    path = [_short(title) for title in tree.path]
    if path:
        parts = [f"Sammlung im Themenbaum unter: {' › '.join(path)}"]
    else:
        parts = [f"Sammlung im Fachportal {subjects[0]}" if subjects else "Sammlung"]
    if tree.children:
        parts.append("ihre Untersammlungen: " + ", ".join(map(_short, tree.children)))
    if tree.materials:
        parts.append("Materialien darin: " + ", ".join(map(_short, tree.materials)))
    if tree.neighbours:
        parts.append("nicht gemeint sind die Nachbarsammlungen: " + ", ".join(map(_short, tree.neighbours)))
    return "; ".join(parts)


def _short(title: str) -> str:
    return " ".join(title.split())[:MAX_TITLE]
