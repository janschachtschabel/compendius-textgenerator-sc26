"""SPARQL query builders for the MEM harvest: pure string construction, unit-testable offline.

SPARQL has no prepared statements, so ``validate_iri`` is the only injection barrier: every IRI that
reaches a query passes through it. Transitive paths are avoided except for the one constant-subject
subselect in ``closure``: Virtuoso answers unbounded paths joined against instance data with HTTP 500,
while the subselect form was measured at 0.8 s for a curriculum of 352 nodes (2026-09-17).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.sources.lehrplan.vocab import (
    CLASS_CE_BEREICH,
    CLASS_CE_FRAGMENT,
    CLASS_CE_INHALT,
    CLASS_CE_KOMPETENZ,
    CLASS_LEHRPLAN,
    HAS_PART,
    MAX_CE_SUBCLASS_DEPTH,
    MAX_INTERSECTION_LIST_LENGTH,
    MAX_TREE_DEPTH,
    ONTOLOGY,
    PREFIXES,
    PROP_BUNDESLAND,
    PROP_FUNKTION,
    PROP_JAHRGANGSSTUFE,
    PROP_POSITION,
    PROP_SCHULART,
    PROP_SCHULFACH,
    PROP_SCHULSTUFE,
)

SEPARATOR = "|"
_IRI_FORBIDDEN = frozenset('<>"{}|^`') | {chr(92)}


def validate_iri(value: str) -> str:
    """Return ``value`` when it is an http(s) IRI that cannot break out of ``<…>``; raise ``ValueError``."""
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"IRI must be http(s): {value!r}")
    if any(ch in _IRI_FORBIDDEN or ch.isspace() or ord(ch) < 32 for ch in value):
        raise ValueError(f"IRI contains forbidden characters: {value!r}")
    return value


def _values(variable: str, iris: Sequence[str]) -> str:
    joined = " ".join(f"<{validate_iri(iri)}>" for iri in iris)
    return f"VALUES ?{variable} {{ {joined} }}"


def _de(variable: str) -> str:
    # State-graph labels are mostly untagged, Saxony tags @de, the ontology adds @en.
    return f'FILTER(LANG({variable}) IN ("de", ""))'


def _head_path(prop: str) -> str:
    """A head field on the Lehrplan itself or on one of its parts (Bavaria's Fachlehrplan child)."""
    return f"(lp:{prop}|{HAS_PART}/lp:{prop})"


def _concat(variable: str, alias: str) -> str:
    return f'(GROUP_CONCAT(DISTINCT ?{variable}; separator="{SEPARATOR}") AS ?{alias})'


def lehrplan_list(bundesland_iri: str, *, limit: int = 500, offset: int = 0) -> str:
    """IRIs and labels of one state's curricula, paged by IRI order (the cheap query; 0.4 s for all)."""
    land = validate_iri(bundesland_iri)
    return f"""{PREFIXES}

SELECT ?s (SAMPLE(?l) AS ?label)
WHERE {{
  ?s a lp:{CLASS_LEHRPLAN} ; lp:{PROP_BUNDESLAND} <{land}> .
  OPTIONAL {{ ?s rdfs:label ?l . {_de("?l")} }}
}}
GROUP BY ?s
ORDER BY ?s
LIMIT {int(limit)}
OFFSET {int(offset)}"""


HEAD_FIELDS = {
    "schulart": PROP_SCHULART,
    "schulfach": PROP_SCHULFACH,
    "jahrgangsstufe": PROP_JAHRGANGSSTUFE,
    "schulstufe": PROP_SCHULSTUFE,
}


def lehrplan_heads(lehrplan_iris: Sequence[str]) -> str:
    """Head field labels (subject, school type, grades, level) of the given curricula, one row each.

    Subject, school type and grades sit on the Lehrplan (SN, RP, BE) or on its Fachlehrplan child
    (BY); one property path asks both places. Bound to a VALUES block of at most a few dozen IRIs:
    the same fields aggregated over a whole state timed out (Berlin, 300 s, 2026-09-17).
    """
    branches = [f'{{ ?s {_head_path(prop)} ?o . BIND("{name}" AS ?field) }}' for name, prop in HEAD_FIELDS.items()]
    union = "\n  UNION ".join(branches)
    return f"""{PREFIXES}

SELECT DISTINCT ?s ?field ?label
WHERE {{
  {_values("s", lehrplan_iris)}
  {union}
  ?o rdfs:label ?label .
  {_de("?label")}
}}"""


def closure(lehrplan_iri: str) -> str:
    """Every part of one curriculum with label, classes, grades, position and its has-part sources.

    The parts are collected once in a subselect through Virtuoso's transitive option with distinct
    tracking. The plain ``BFO_0000051+`` exhausted the transitive memory on a curriculum of 121
    nodes, because the states materialise has-part as a closure and every path was counted;
    fixed-length path unions cannot know how deep a tree goes; ``t_distinct`` answers a 1,007-node
    curriculum in 0.5 s (2026-09-17). ``tree.build_nodes`` turns the ancestor lists into real parents.
    """
    subject = validate_iri(lehrplan_iri)
    return f"""{PREFIXES}

SELECT ?n (SAMPLE(?l) AS ?label)
       {_concat("t", "types")}
       {_concat("gl", "jahrgaenge")}
       (SAMPLE(?pos) AS ?position)
       {_concat("a", "ancestors")}
WHERE {{
  {{ SELECT DISTINCT ?n WHERE {{
      <{subject}> {HAS_PART} ?n OPTION (TRANSITIVE, t_distinct, t_min(1), t_max({MAX_TREE_DEPTH})) .
  }} }}
  OPTIONAL {{ ?n rdfs:label ?l . {_de("?l")} }}
  OPTIONAL {{ ?n rdf:type ?t . FILTER(STRSTARTS(STR(?t), "{ONTOLOGY}")) }}
  OPTIONAL {{ ?n lp:{PROP_JAHRGANGSSTUFE} ?g . ?g rdfs:label ?gl . {_de("?gl")} }}
  OPTIONAL {{ ?n lp:{PROP_POSITION} ?pos . }}
  OPTIONAL {{ ?a {HAS_PART} ?n . }}
}}
GROUP BY ?n"""


def _list_members(list_var: str, member_var: str, max_length: int) -> str:
    branches = []
    for position in range(max_length):
        rests = "/".join(["rdf:rest"] * position)
        path = f"{rests}/rdf:first" if rests else "rdf:first"
        branches.append(f"{{ ?{list_var} {path} ?{member_var} }}")
    return "\n    UNION ".join(branches)


def _subclass_paths(subject_var: str, object_var: str, max_depth: int) -> str:
    branches = [
        f"{{ ?{subject_var} {'/'.join(['rdfs:subClassOf'] * depth)} ?{object_var} }}"
        for depth in range(1, max_depth + 1)
    ]
    return "\n    UNION ".join(branches)


def class_roles(type_iris: Sequence[str]) -> str:
    """Label, function individual and CE super-class of node classes (ontology graph).

    The ontology encodes the didactic role twice: competency and content classes pin ``LP_0000483``
    to a function individual inside an anonymous intersection; structuring classes use a plain
    ``rdfs:subClassOf`` chain up to a CE core class. Both paths are bounded UNIONs, no ``*``.
    """
    ce_values = " ".join(
        f"lp:{local}" for local in (CLASS_CE_BEREICH, CLASS_CE_KOMPETENZ, CLASS_CE_INHALT, CLASS_CE_FRAGMENT)
    )
    return f"""{PREFIXES}

SELECT DISTINCT ?type ?typeLabel ?funktion ?ceSuper
WHERE {{
  {_values("type", type_iris)}
  OPTIONAL {{ ?type rdfs:label ?typeLabel . {_de("?typeLabel")} }}
  OPTIONAL {{
    ?type rdfs:subClassOf ?intersection .
    ?intersection owl:intersectionOf ?list .
    {_list_members("list", "restriction", MAX_INTERSECTION_LIST_LENGTH)}
    ?restriction owl:onProperty lp:{PROP_FUNKTION} ;
                 owl:hasValue ?funktion .
  }}
  OPTIONAL {{
    VALUES ?ceSuper {{ {ce_values} }}
    {_subclass_paths("type", "ceSuper", MAX_CE_SUBCLASS_DEPTH)}
  }}
}}"""


def count_lehrplaene() -> str:
    """Number of curricula per state; the weekly change check compares it with the last harvest."""
    return f"""{PREFIXES}

SELECT ?bl (COUNT(DISTINCT ?lp) AS ?n)
WHERE {{ ?lp a lp:{CLASS_LEHRPLAN} ; lp:{PROP_BUNDESLAND} ?bl . }}
GROUP BY ?bl"""
