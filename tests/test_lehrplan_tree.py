"""Closure rows from the store become nodes with real parents and didactic roles."""

from app.sources.lehrplan.tree import build_class_index, build_nodes, roles_for
from app.sources.lehrplan.vocab import ONTOLOGY

LP = ONTOLOGY


def _row(iri: str, label: str, *ancestors: str, **fields: str) -> dict[str, str]:
    row = {"n": iri, "label": label, "ancestors": "|".join(ancestors)}
    row.update(fields)
    return row


def _bavarian_closure() -> list[dict[str, str]]:
    """1 -> 4 -> 47 as the store hands it over: every leaf names the root and its branch as ancestors."""
    rows = [_row("n:root", "Fachlehrplan", "n:lehrplan", types=LP + "LP_0002043")]
    for branch in range(1, 5):
        rows.append(_row(f"n:b{branch}", f"Lernbereich {branch}", "n:lehrplan", "n:root", types=LP + "LP_0002046"))
    leaf = 0
    for branch in range(1, 5):
        for _ in range(12 if branch < 4 else 11):
            leaf += 1
            rows.append(
                _row(
                    f"n:l{leaf:02d}",
                    f"Kompetenz {leaf:02d}",
                    "n:lehrplan",
                    "n:root",
                    f"n:b{branch}",
                    types=LP + "LP_0000263",
                )
            )
    return rows


def test_materialised_closure_collapses_to_the_true_tree() -> None:
    nodes = {node.iri: node for node in build_nodes(_bavarian_closure(), index={})}
    assert len(nodes) == 52
    assert nodes["n:root"].parent_iri is None  # the Lehrplan itself is not among the parts
    assert nodes["n:root"].depth == 0
    assert nodes["n:b2"].parent_iri == "n:root" and nodes["n:b2"].depth == 1
    assert nodes["n:l13"].parent_iri == "n:b2"
    assert nodes["n:l13"].parent_label == "Lernbereich 2"
    assert nodes["n:l13"].depth == 2
    assert nodes["n:l47"].parent_iri == "n:b4"


def test_direct_edges_only_give_the_same_tree() -> None:
    rows = [
        _row("n:root", "Lehrplanfragment", "n:lehrplan"),
        _row("n:lb", "Lernbereich 2: Optik", "n:root", jahrgaenge="Klassenstufe 7"),
        _row("n:k", "Lichtbrechung an Linsen", "n:lb", position="3"),
    ]
    nodes = {node.iri: node for node in build_nodes(rows, index={})}
    assert nodes["n:k"].parent_iri == "n:lb" and nodes["n:k"].depth == 2
    assert nodes["n:k"].position == 3
    assert nodes["n:lb"].jahrgangsstufen == ["Klassenstufe 7"]
    assert nodes["n:k"].jahrgangsstufen == []


def test_roles_come_from_ce_class_class_index_or_override() -> None:
    index = build_class_index(
        [
            {"type": LP + "LP_0002115", "typeLabel": "Lernziel und Lerninhalt (SN)", "funktion": LP + "LP_0000479"},
            {"type": LP + "LP_0002115", "typeLabel": "Lernziel und Lerninhalt (SN)", "funktion": LP + "LP_0000480"},
            {
                "type": LP + "LP_0000431",
                "typeLabel": "Kompetenzbereich (RP)",
                "funktion": LP + "LP_0000497",
                "ceSuper": LP + "LP_0000349",
            },
            {"type": LP + "LP_0002110", "typeLabel": "Lehrplanfragment (SN)", "funktion": LP + "LP_0000627"},
        ]
    )
    assert roles_for([LP + "LP_0000263", LP + "LP_0001447"], index) == ["kompetenz"]  # Berlin: CE class stated
    assert roles_for([LP + "LP_0002115"], index) == ["kompetenz", "inhalt"]  # Saxony: two functions
    assert roles_for([LP + "LP_0000431"], index) == ["themenbereich"]
    assert roles_for([LP + "LP_0002110"], index) == ["fragment"]
    assert roles_for([LP + "LP_0000429"], index) == ["themenbereich"]  # Themenfeld only via override
    assert roles_for([LP + "LP_0000261", "http://purl.obolibrary.org/obo/BFO_0000001"], index) == ["unbekannt"]
    assert index[LP + "LP_0002115"].label == "Lernziel und Lerninhalt (SN)"


def test_missing_labels_fall_back_to_the_iri_tail_and_cycles_do_not_hang() -> None:
    rows = [_row("https://lp-x.org/resource/a-1", "", "n:b"), _row("n:b", "B", "https://lp-x.org/resource/a-1")]
    nodes = {node.iri: node for node in build_nodes(rows, index={})}
    assert nodes["https://lp-x.org/resource/a-1"].label == "a-1"
    assert all(node.depth >= 0 for node in nodes.values())
