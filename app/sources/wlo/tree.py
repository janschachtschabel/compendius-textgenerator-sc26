"""Where a collection stands in its topic tree (M71): the collections above it, what lies in it, and its neighbours.

A collection named "Grundlagen" or "Methoden" says what it is about only with its place in the tree. The collections
above it name the field ("Kernphysik"); its own sub-collections and the titles of its first materials name what it
holds; its neighbours - the other sub-collections of its parent - name what it does not hold. Only the first two are
its content; the neighbours serve to tell it apart and are never read as content (Jan, 2026-10-08: selective, nothing
that rather belongs to other collections of the tree).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from app.sources.wlo.client import EduSharingError, Remaining
from app.sources.wlo.models import SubCollection
from app.sources.wlo.part import CollectionBuilder

log = logging.getLogger(__name__)

MAX_PATH = 3  # collections above, below the subject portal
MAX_CHILDREN = 10
MAX_MATERIALS = 8
MAX_NEIGHBOURS = 10
_ROOTS = frozenset({"WLO"})  # the root of the WLO trees; a portal is named after its subject


@dataclass(frozen=True)
class TreeContext:
    """The place of a collection in its topic tree; every part may be empty."""

    path: tuple[str, ...] = ()  # the collections above it, the nearest last, without the subject portal and the root
    children: tuple[str, ...] = ()  # its own sub-collections
    materials: tuple[str, ...] = ()  # the titles of its first materials
    neighbours: tuple[str, ...] = ()  # the other sub-collections of its parent: for telling apart, never content
    missing: tuple[str, ...] = ()  # the parts the repository did not give: path, children, materials, neighbours


def read_tree(
    builder: CollectionBuilder,
    collection_id: str,
    parent_id: str,
    subjects: Sequence[str],
    *,
    remaining: Remaining | None = None,
    content: bool = True,
) -> TreeContext:
    """The tree around ``collection_id``, read through ``builder`` and its cache within ``remaining``. The path ends
    below the collection named after one of ``subjects`` (the subject portal) and at the root; the sub-collections,
    materials and neighbours are read only with ``content``. A part the repository fails to give, or one the time
    budget has no room for, stays empty and is named in ``missing``: the context helps, the request does not depend on
    it."""
    missing: list[str] = []
    path = _path(builder, parent_id, subjects, remaining, missing)
    if not content:
        return TreeContext(path=path, missing=tuple(missing))

    def children() -> tuple[str, ...]:
        return _titles(builder.subcollections(collection_id, remaining=remaining))[:MAX_CHILDREN]

    def materials() -> tuple[str, ...]:
        return builder.first_materials(collection_id, MAX_MATERIALS, remaining=remaining)

    def neighbours() -> tuple[str, ...]:
        siblings = builder.subcollections(parent_id, remaining=remaining) if parent_id else []
        return _titles(s for s in siblings if s.id != collection_id)[:MAX_NEIGHBOURS]

    return TreeContext(
        path=path,
        children=_guarded(children, collection_id, "children", missing),
        materials=_guarded(materials, collection_id, "materials", missing),
        neighbours=_guarded(neighbours, collection_id, "neighbours", missing),
        missing=tuple(missing),
    )


def _path(
    builder: CollectionBuilder,
    parent_id: str,
    subjects: Sequence[str],
    remaining: Remaining | None,
    missing: list[str],
) -> tuple[str, ...]:
    """The titles of the collections above, the nearest last; what was read before a failure stays."""
    found: list[str] = []
    above = parent_id
    try:
        while above and len(found) < MAX_PATH:
            info = builder.info(above, remaining=remaining)
            if not info.title or info.title in subjects or info.title in _ROOTS or info.title.isdigit():
                break  # the subject portal, the root, or the numbered root above it
            found.insert(0, info.title)
            above = info.parent_id
    except EduSharingError as exc:  # TimeUpError included
        log.warning("topic tree above collection %s read as far as %d levels: %s", parent_id, len(found), exc)
        missing.append("path")
    return tuple(found)


def _titles(subs: Iterable[SubCollection]) -> tuple[str, ...]:
    return tuple(sub.title for sub in subs if sub.title.strip())


def _guarded(read: Callable[[], tuple[str, ...]], collection_id: str, what: str, missing: list[str]) -> tuple[str, ...]:
    try:
        return read()
    except EduSharingError as exc:  # TimeUpError included
        log.warning("topic tree of collection %s without its %s: %s", collection_id, what, exc)
        missing.append(what)
        return ()
