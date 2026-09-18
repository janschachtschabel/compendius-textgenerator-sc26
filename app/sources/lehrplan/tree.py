"""Closure rows of one curriculum become nodes with real parents and didactic roles (PLAN.md 5.2).

Bavaria and Berlin materialise has-part as a closure: a leaf names the curriculum root and its own
branch as ancestors alike. Saxony states only the direct parts. Both read the same way: the real
parent of a node is the ancestor that has the most ancestors itself. Roles come from the generic CE
class where a node states one (BY, BE), from the class index otherwise (SN, RP; ``class_roles``
query), and from a small override table for classes the ontology leaves unplaced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.sources.lehrplan.queries import SEPARATOR
from app.sources.lehrplan.vocab import (
    CE_ROLES,
    FUNCTION_ROLES,
    MATCHABLE_ROLES,
    ROLE_ORDER,
    ROLE_OVERRIDES,
    ROLE_UNBEKANNT,
)


@dataclass
class ClassInfo:
    """What the ontology says about one node class."""

    iri: str
    label: str = ""
    functions: set[str] = field(default_factory=set)
    ce_superclasses: set[str] = field(default_factory=set)

    @property
    def roles(self) -> list[str]:
        roles = {FUNCTION_ROLES[f] for f in self.functions if f in FUNCTION_ROLES}
        roles |= {CE_ROLES[c] for c in self.ce_superclasses if c in CE_ROLES}
        return [role for role in ROLE_ORDER if role in roles]


@dataclass
class HarvestedNode:
    """One curriculum element as it goes into the cache."""

    iri: str
    label: str
    types: tuple[str, ...]
    rollen: list[str]
    jahrgangsstufen: list[str]
    position: int | None
    parent_iri: str | None = None
    parent_label: str = ""
    depth: int = 0


def build_class_index(rows: Sequence[Mapping[str, str]]) -> dict[str, ClassInfo]:
    """Fold ``class_roles`` rows (one per function or super-class) into one entry per class."""
    index: dict[str, ClassInfo] = {}
    for row in rows:
        iri = row.get("type")
        if not iri:
            continue
        info = index.setdefault(iri, ClassInfo(iri=iri))
        if not info.label and row.get("typeLabel"):
            info.label = row["typeLabel"]
        if row.get("funktion"):
            info.functions.add(row["funktion"])
        if row.get("ceSuper"):
            info.ce_superclasses.add(row["ceSuper"])
    return index


def roles_for(type_iris: Sequence[str], index: Mapping[str, ClassInfo]) -> list[str]:
    """Roles of a node typed with ``type_iris``: content roles win over structural ones.

    A Berlin Standard is typed as CE-Kompetenzspezifikation and as Element (BE); the latter is a
    wrapper (fragment) and must not make the competency look structural.
    """
    roles: set[str] = set()
    for iri in type_iris:
        if iri in CE_ROLES:
            roles.add(CE_ROLES[iri])
        info = index.get(iri)
        if info is not None:
            roles.update(info.roles)
        if iri in ROLE_OVERRIDES:
            roles.add(ROLE_OVERRIDES[iri])
    content = [role for role in ROLE_ORDER if role in roles and role in MATCHABLE_ROLES]
    if content:
        return content
    return [role for role in ROLE_ORDER if role in roles] or [ROLE_UNBEKANNT]


def build_nodes(rows: Sequence[Mapping[str, str]], index: Mapping[str, ClassInfo]) -> list[HarvestedNode]:
    """Turn closure rows into nodes with parent, parent label and depth.

    Ancestors outside the rows (the Lehrplan itself) do not count, so the top elements are roots.
    """
    nodes: dict[str, HarvestedNode] = {}
    ancestors: dict[str, set[str]] = {}
    for row in rows:
        iri = row["n"]
        types = _split(row.get("types", ""))
        nodes[iri] = HarvestedNode(
            iri=iri,
            label=row.get("label") or _tail(iri),
            types=types,
            rollen=roles_for(types, index),
            jahrgangsstufen=list(_split(row.get("jahrgaenge", ""))),
            position=_integer(row.get("position")),
        )
        ancestors[iri] = set(_split(row.get("ancestors", "")))
    for iri, known in ancestors.items():
        known.intersection_update(nodes)
        known.discard(iri)

    for node in nodes.values():
        candidates = ancestors[node.iri]
        if not candidates:
            continue
        deepest = max(len(ancestors[candidate]) for candidate in candidates)
        parent = min(
            (candidate for candidate in candidates if len(ancestors[candidate]) == deepest),
            key=lambda candidate: (nodes[candidate].label, candidate),
        )
        node.parent_iri = parent
        node.parent_label = nodes[parent].label
    for node in nodes.values():
        node.depth = _depth(node, nodes)
    return list(nodes.values())


def _depth(node: HarvestedNode, nodes: Mapping[str, HarvestedNode]) -> int:
    depth, seen, current = 0, {node.iri}, node
    while current.parent_iri is not None and current.parent_iri in nodes:
        if current.parent_iri in seen:  # a cycle in the data; stop counting instead of looping
            break
        seen.add(current.parent_iri)
        current = nodes[current.parent_iri]
        depth += 1
    return depth


def _split(concatenated: str) -> tuple[str, ...]:
    return tuple(part for part in concatenated.split(SEPARATOR) if part)


def _integer(value: str | None) -> int | None:
    return int(value) if value and value.strip().isdigit() else None


def _tail(iri: str) -> str:
    return iri.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
