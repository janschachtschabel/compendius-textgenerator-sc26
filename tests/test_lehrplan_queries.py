"""SPARQL query builders for the MEM harvest: verified vocabulary, safe interpolation, bounded paths."""

import pytest

from app.sources.lehrplan import queries
from app.sources.lehrplan.vocab import BUNDESLAENDER, ONTOLOGY, bundesland_by_code

LP = ONTOLOGY


def test_all_sixteen_states_with_code_and_terminology() -> None:
    assert len(BUNDESLAENDER) == 16
    assert len({b.code for b in BUNDESLAENDER}) == 16
    assert bundesland_by_code("BY").iri == LP + "LP_3000051"
    assert bundesland_by_code("BY").terminology == "LehrplanPLUS"
    assert bundesland_by_code("SH").terminology == "Fachanforderungen"
    assert bundesland_by_code("NW").terminology == "Kernlehrplan"
    assert bundesland_by_code("sn").name == "Sachsen"
    with pytest.raises(KeyError):
        bundesland_by_code("XX")


@pytest.mark.parametrize(
    "bad", ["", "ftp://x", "https://a b", 'https://x/"> . ?s ?p ?o', "https://x/{y}", "https://x/<y>"]
)
def test_iri_validation_refuses_what_could_break_out_of_the_brackets(bad: str) -> None:
    with pytest.raises(ValueError):
        queries.validate_iri(bad)


def test_iri_validation_accepts_store_iris() -> None:
    iri = "https://lp-sachsen.org/resource/lehrplan-130-1"
    assert queries.validate_iri(iri) == iri


def test_list_query_pages_one_states_curricula_by_iri() -> None:
    query = queries.lehrplan_list(LP + "LP_3000051", limit=500, offset=1000)
    assert "?s a lp:LP_0000438" in query
    assert f"lp:LP_0000029 <{LP}LP_3000051>" in query
    assert query.rstrip().endswith("ORDER BY ?s\nLIMIT 500\nOFFSET 1000")
    assert "GROUP BY ?s" in query
    # An unlabeled curriculum must still be listed, or the count check would report a change forever
    assert "OPTIONAL { ?s rdfs:label ?l ." in query


def test_heads_query_reads_head_fields_from_the_lehrplan_and_its_fachlehrplan_child() -> None:
    iris = ["https://lp-bavaria.org/lehrplanplus-lis_live_isb.c.86605.de", "https://lp-sachsen.org/resource/522"]
    query = queries.lehrplan_heads(iris)
    assert f"VALUES ?s {{ <{iris[0]}> <{iris[1]}> }}" in query
    # Bavaria keeps subject, school type and grades on the Fachlehrplan child (measured 2026-09-02)
    assert "(lp:LP_0000537|obo:BFO_0000051/lp:LP_0000537)" in query
    assert "(lp:LP_0000812|obo:BFO_0000051/lp:LP_0000812)" in query
    assert "(lp:LP_0000026|obo:BFO_0000051/lp:LP_0000026)" in query
    assert "(lp:LP_0000047|obo:BFO_0000051/lp:LP_0000047)" in query
    for name in ("schulart", "schulfach", "jahrgangsstufe", "schulstufe"):
        assert f'BIND("{name}" AS ?field)' in query
    assert "?s ?field ?label" in query


def test_closure_query_collects_all_parts_once_with_distinct_transitive_tracking() -> None:
    query = queries.closure("https://lp-rlp.org/resource/lehrplan-146-1")
    assert "{ SELECT DISTINCT ?n WHERE {" in query
    walk = "<https://lp-rlp.org/resource/lehrplan-146-1> obo:BFO_0000051 ?n OPTION (TRANSITIVE, t_distinct, t_min(1), t_max(30))"
    assert walk in query
    # The plain transitive operator ran out of memory on a real curriculum (2026-09-17); never again
    assert "BFO_0000051+" not in query and "BFO_0000051*" not in query
    assert "?a obo:BFO_0000051 ?n" in query
    assert "GROUP BY ?n" in query
    for variable in ("?label", "?types", "?jahrgaenge", "?position", "?ancestors"):
        assert variable in query


def test_class_roles_query_walks_bounded_subclass_paths_only() -> None:
    query = queries.class_roles([LP + "LP_0002115", LP + "LP_0000432"])
    assert f"VALUES ?type {{ <{LP}LP_0002115> <{LP}LP_0000432> }}" in query
    assert "owl:onProperty lp:LP_0000483" in query
    assert "rdfs:subClassOf/rdfs:subClassOf/rdfs:subClassOf/rdfs:subClassOf ?ceSuper" in query
    assert "rdfs:subClassOf*" not in query and "rdfs:subClassOf+" not in query


def test_count_query_groups_curricula_by_state() -> None:
    query = queries.count_lehrplaene()
    assert "COUNT(DISTINCT ?lp)" in query and "GROUP BY ?bl" in query
