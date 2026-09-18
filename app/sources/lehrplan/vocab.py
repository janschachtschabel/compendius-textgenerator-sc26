"""Verified IRIs of the MEM Lehrplan ontology (``https://w3id.org/lehrplan/ontology/``, 1.0.0rc3).

Every IRI here was checked against ``lp.ttl`` (FWU-DE/lehrplan-ontologie) or measured on the endpoint
(PLAN.md 5.1, probes of 2026-09-17). Do not add entries from memory. The Virtuoso endpoint performs no
RDFS reasoning, but its ``…/inferences`` graphs hold the materialised class closure, so
``?lp a lp:LP_0000438`` finds the state-typed curricula directly (0.4 s for all 2,514).
"""

from __future__ import annotations

from dataclasses import dataclass

ONTOLOGY = "https://w3id.org/lehrplan/ontology/"
ONTOLOGY_VERSION = "1.0.0rc3"
DEFAULT_ENDPOINT = "https://sparql.mem.edufeed.org/sparql/"

PREFIXES = """PREFIX lp:   <https://w3id.org/lehrplan/ontology/>
PREFIX obo:  <http://purl.obolibrary.org/obo/>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>"""

# Classes (local names; prefix with ``lp:`` in queries or with ``ONTOLOGY`` for full IRIs)
CLASS_LEHRPLAN = "LP_0000438"
CLASS_CE_BEREICH = "LP_0000349"
CLASS_CE_KOMPETENZ = "LP_0000263"
CLASS_CE_INHALT = "LP_0000332"
CLASS_CE_FRAGMENT = "LP_0001015"
CLASS_CE_HINWEIS = "LP_0000852"
CLASS_CE_VERWEIS = "LP_0030065"
CLASS_JAHRGANGSSTUFE = "LP_0000009"
CLASS_SCHULSTUFE = "LP_0000020"

# Properties
HAS_PART = "obo:BFO_0000051"  # the tree edge; the state graphs materialise its closure
PROP_BUNDESLAND = "LP_0000029"
PROP_SCHULFACH = "LP_0000537"
PROP_SCHULART = "LP_0000812"
PROP_JAHRGANGSSTUFE = "LP_0000026"
PROP_SCHULSTUFE = "LP_0000047"
PROP_BESCHRIEBEN_VON = "LP_0000024"  # generic super-property; Berlin asserts it instead of the specific ones
PROP_FUNKTION = "LP_0000483"  # has function specification
PROP_POSITION = "LP_0000460"

# Didactic roles of curriculum nodes
ROLE_THEMENBEREICH = "themenbereich"
ROLE_KOMPETENZ = "kompetenz"
ROLE_INHALT = "inhalt"
ROLE_FRAGMENT = "fragment"
ROLE_HINWEIS = "hinweis"
ROLE_VERWEIS = "verweis"
ROLE_UNBEKANNT = "unbekannt"
ROLE_ORDER = (ROLE_THEMENBEREICH, ROLE_KOMPETENZ, ROLE_INHALT, ROLE_FRAGMENT, ROLE_HINWEIS, ROLE_VERWEIS)
MATCHABLE_ROLES = frozenset({ROLE_THEMENBEREICH, ROLE_KOMPETENZ, ROLE_INHALT})

# Function individuals pinned via owl:hasValue in the anonymous intersection of a state class
FUNCTION_ROLES = {
    ONTOLOGY + "LP_0000497": ROLE_THEMENBEREICH,  # Bereichsfunktion
    ONTOLOGY + "LP_0000479": ROLE_KOMPETENZ,  # Kompetenzbeschreibungsfunktion
    ONTOLOGY + "LP_0000480": ROLE_INHALT,  # Lerninhaltsbeschreibungsfunktion
    ONTOLOGY + "LP_0000627": ROLE_FRAGMENT,  # Gliederungsfunktion (Lehrplanfragment)
}
# Generic CE classes; Bavaria and Berlin type their nodes with these beside the state class
CE_ROLES = {
    ONTOLOGY + CLASS_CE_BEREICH: ROLE_THEMENBEREICH,
    ONTOLOGY + CLASS_CE_KOMPETENZ: ROLE_KOMPETENZ,
    ONTOLOGY + CLASS_CE_INHALT: ROLE_INHALT,
    ONTOLOGY + CLASS_CE_FRAGMENT: ROLE_FRAGMENT,
    ONTOLOGY + CLASS_CE_HINWEIS: ROLE_HINWEIS,
    ONTOLOGY + CLASS_CE_VERWEIS: ROLE_VERWEIS,
}
# State classes that carry neither a function nor a CE ancestor in 1.0.0rc3
# (lehrplan-ontologien, MEM import plan of 2026-09-02, checked on the endpoint 2026-09-17)
ROLE_OVERRIDES = {
    ONTOLOGY + "LP_0000429": ROLE_THEMENBEREICH,  # Themenfeld; structure.md §2 counts it as CE-Bereich
    ONTOLOGY + "LP_0001441": ROLE_FRAGMENT,  # Element (BE), generic wrapper class
    ONTOLOGY + "LP_0002043": ROLE_FRAGMENT,  # Fachlehrplan (BY), the head node below a Bavarian Lehrplan
}

# Bounded path lengths replacing transitive paths (measured on lp.ttl by the prototype, one step margin)
MAX_CE_SUBCLASS_DEPTH = 4
MAX_INTERSECTION_LIST_LENGTH = 8
# t_max of the transitive walk that collects a curriculum's parts (Virtuoso option); the deepest tree
# measured is 8 levels (Saxony, 2026-09-17). The harvest warns when a node reaches this bound.
MAX_TREE_DEPTH = 30


@dataclass(frozen=True)
class Bundesland:
    code: str
    name: str
    iri: str
    terminology: str  # what the state calls its curriculum documents (rendering, PLAN.md 5.1)


def _land(local: str, code: str, name: str, terminology: str) -> Bundesland:
    return Bundesland(code=code, name=name, iri=ONTOLOGY + local, terminology=terminology)


# Named individuals enumerated by owl:oneOf on LP_0000040 (Bundesland Bezeichnung)
BUNDESLAENDER: tuple[Bundesland, ...] = (
    _land("LP_3000049", "BW", "Baden-Württemberg", "Bildungsplan"),
    _land("LP_3000051", "BY", "Bayern", "LehrplanPLUS"),
    _land("LP_3000048", "BE", "Berlin", "Rahmenlehrplan"),
    _land("LP_3000057", "BB", "Brandenburg", "Rahmenlehrplan"),
    _land("LP_3000056", "HB", "Bremen", "Bildungsplan"),
    _land("LP_3000045", "HH", "Hamburg", "Bildungsplan"),
    _land("LP_3000050", "HE", "Hessen", "Kerncurriculum"),
    _land("LP_3000052", "MV", "Mecklenburg-Vorpommern", "Rahmenplan"),
    _land("LP_3000043", "NI", "Niedersachsen", "Kerncurriculum"),
    _land("LP_3000044", "NW", "Nordrhein-Westfalen", "Kernlehrplan"),
    _land("LP_3000046", "RP", "Rheinland-Pfalz", "Lehrplan"),
    _land("LP_3000055", "SL", "Saarland", "Lehrplan"),
    _land("LP_3000047", "SN", "Sachsen", "Lehrplan"),
    _land("LP_3000053", "ST", "Sachsen-Anhalt", "Fachlehrplan"),
    _land("LP_3000054", "SH", "Schleswig-Holstein", "Fachanforderungen"),
    _land("LP_3000031", "TH", "Thüringen", "Lehrplan"),
)
_BY_CODE = {land.code: land for land in BUNDESLAENDER}
_BY_IRI = {land.iri: land for land in BUNDESLAENDER}


def bundesland_by_code(code: str) -> Bundesland:
    """The state for a two-letter code (case-insensitive); ``KeyError`` for unknown codes."""
    return _BY_CODE[code.upper()]


def bundesland_by_iri(iri: str) -> Bundesland | None:
    return _BY_IRI.get(iri)
