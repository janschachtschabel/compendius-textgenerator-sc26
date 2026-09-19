"""SQLite cache of harvested curricula: atomic replace, substring search with subject filter."""

from pathlib import Path

import pytest

from app.sources.lehrplan.store import LehrplanCacheError, LehrplanRecord, LehrplanStore, LehrplanWriter
from app.sources.lehrplan.tree import HarvestedNode

PHYSIK = LehrplanRecord(
    iri="https://lp-sachsen.org/resource/522",
    label="Gymnasium Physik",
    bundesland_code="SN",
    bundesland="Sachsen",
    schularten=["Gymnasium"],
    schulfaecher=["Physik"],
    jahrgangsstufen=["Klassenstufe 6", "Klassenstufe 7"],
    schulstufen=["Sekundarbereich I"],
)
CHEMIE = LehrplanRecord(
    iri="https://lp-rlp.org/resource/lehrplan-9",
    label="Chemie Sekundarstufe I",
    bundesland_code="RP",
    bundesland="Rheinland-Pfalz",
    schularten=[],
    schulfaecher=["Chemie"],
    jahrgangsstufen=[],
    schulstufen=[],
)


def _node(iri: str, label: str, rollen: list[str], parent: str = "", **fields: object) -> HarvestedNode:
    node = HarvestedNode(iri=iri, label=label, types=(), rollen=rollen, jahrgangsstufen=[], position=None)
    node.parent_label = parent
    for key, value in fields.items():
        setattr(node, key, value)
    return node


def _write(path: Path) -> LehrplanStore:
    writer = LehrplanWriter(path)
    writer.add_lehrplan(PHYSIK)
    writer.add_nodes(
        PHYSIK.iri,
        [
            _node("n:1", "Lernbereich 4: Wellenoptik", ["themenbereich"], jahrgangsstufen=["Klassenstufe 7"]),
            _node("n:2", "Lichtbrechung an Linsen", ["kompetenz", "inhalt"], "Lernbereich 2: Optik", depth=2),
            _node("n:3", "Ziele und Aufgaben", ["fragment"]),
            _node("n:4", "Wahlpflichtlernbereich 9: Astrophysik", ["themenbereich"]),
        ],
    )
    writer.add_lehrplan(CHEMIE)
    writer.add_nodes(CHEMIE.iri, [_node("n:5", "Säure-Base-Reaktionen", ["kompetenz"], "Optik der Farben")])
    writer.set_meta({"harvested_at": "2026-09-17T10:00:00+00:00", "endpoint": "https://sparql.test/"})
    writer.commit()
    return LehrplanStore(path)


def test_writer_commits_atomically_and_reports_counts(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.db"
    store = _write(path)
    assert store.exists
    assert not path.with_name("lehrplan.db.tmp").exists()
    assert store.meta()["harvested_at"] == "2026-09-17T10:00:00+00:00"
    counts = store.counts()
    assert counts["lehrplaene"] == {"SN": 1, "RP": 1}
    assert counts["nodes"] == 5


def test_search_matches_substrings_in_label_or_parent_case_insensitively(tmp_path: Path) -> None:
    store = _write(tmp_path / "lehrplan.db")
    hits = {hit.iri: hit for hit in store.search(["Optik"])}
    assert set(hits) == {"n:1", "n:2", "n:5"}
    assert hits["n:1"].matched_in == "label"
    assert hits["n:2"].matched_in == "parent" and hits["n:2"].parent_label == "Lernbereich 2: Optik"
    assert hits["n:2"].lehrplan.label == "Gymnasium Physik" and hits["n:2"].lehrplan.bundesland_code == "SN"
    assert hits["n:1"].jahrgangsstufen == ["Klassenstufe 7"]
    assert [hit.iri for hit in store.search(["SÄURE"])] == ["n:5"]


def test_search_filters_by_subject_terms_and_ignores_structural_nodes(tmp_path: Path) -> None:
    store = _write(tmp_path / "lehrplan.db")
    assert {hit.iri for hit in store.search(["Optik"], subject_terms=["physik"])} == {"n:1", "n:2"}
    assert {hit.iri for hit in store.search(["Optik"], subject_terms=["chemie", "natur und technik"])} == {"n:5"}
    assert store.search(["Aufgaben"]) == []  # a fragment (structural) node is never a hit
    assert store.search(["Op"]) == []  # shorter than a trigram
    assert store.search([]) == []


def test_missing_database_is_reported_not_raised(tmp_path: Path) -> None:
    store = LehrplanStore(tmp_path / "missing.db")
    assert not store.exists
    assert store.search(["Optik"]) == []
    assert store.meta() == {}
    assert store.counts() == {"lehrplaene": {}, "nodes": 0}


def test_abort_keeps_the_previous_database(tmp_path: Path) -> None:
    path = tmp_path / "lehrplan.db"
    _write(path)
    writer = LehrplanWriter(path)
    writer.add_lehrplan(CHEMIE)
    writer.abort()
    assert not path.with_name("lehrplan.db.tmp").exists()
    assert LehrplanStore(path).counts()["nodes"] == 5
    with pytest.raises(RuntimeError):
        writer.commit()


def test_cache_is_available_only_with_the_current_schema_version(tmp_path: Path) -> None:
    import sqlite3
    from contextlib import closing

    path = tmp_path / "lehrplan.db"
    store = _write(path)
    assert store.available and store.meta()["schema_version"] == "1"
    with closing(sqlite3.connect(path)) as connection:  # sqlite3's own context manager commits but never closes
        connection.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
        connection.commit()
    assert store.exists and not store.available
    with pytest.raises(LehrplanCacheError):  # zero matches from an unusable cache would look like an answer
        store.search(["Optik"])
    path.write_bytes(b"not a database at all")
    assert store.exists and not store.available  # a corrupt file is reported, not raised
    assert store.meta() == {}
    with pytest.raises(LehrplanCacheError):
        store.search(["Optik"])


def test_subject_filter_falls_back_to_the_curriculum_title(tmp_path: Path) -> None:
    """Saxony references unlabeled subject individuals for most curricula; the title still names the subject."""
    writer = LehrplanWriter(tmp_path / "lehrplan.db")
    unlabeled = LehrplanRecord(
        iri="https://lp-sachsen.org/resource/lehrplan-226-1",
        label="Fachoberschule Angewandte Physik",
        bundesland_code="SN",
        bundesland="Sachsen",
    )
    writer.add_lehrplan(unlabeled)
    writer.add_nodes(unlabeled.iri, [_node("n:9", "Optische Abbildungen", ["kompetenz"])])
    writer.commit()
    store = LehrplanStore(tmp_path / "lehrplan.db")
    assert [hit.iri for hit in store.search(["Optische"], subject_terms=["physik"])] == ["n:9"]
    assert store.search(["Optische"], subject_terms=["chemie"]) == []


def test_the_state_tells_a_missing_from_an_unreadable_cache(tmp_path: Path) -> None:
    store = LehrplanStore(tmp_path / "lehrplan.db")
    assert store.state == "missing"
    store.path.write_bytes(b"not a database at all")
    assert store.state == "unreadable" and not store.available
    _write(store.path)
    assert store.state == "ok" and store.available
