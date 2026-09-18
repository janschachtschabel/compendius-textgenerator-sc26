"""Full harvest into the SQLite cache with a fake endpoint: all states asked, roles resolved, atomic swap."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.sources.lehrplan.harvest import STATUS_FILE, LehrplanHarvest, read_status
from app.sources.lehrplan.sparql import SparqlError
from app.sources.lehrplan.store import LehrplanStore
from app.sources.lehrplan.vocab import ONTOLOGY, bundesland_by_code

LP = ONTOLOGY
SN, BE = bundesland_by_code("SN"), bundesland_by_code("BE")
T0 = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)

LISTS = {
    SN.iri: [{"s": "https://lp-sachsen.org/resource/522", "label": "Gymnasium Physik"}],
    BE.iri: [{"s": "https://lehrplan.yovisto.com/resource/lp/be/curriculum/28", "label": "Physik"}],
}
HEADS = [
    {"s": "https://lp-sachsen.org/resource/522", "field": "schulfach", "label": "Physik"},
    {"s": "https://lp-sachsen.org/resource/522", "field": "schulart", "label": "Gymnasium"},
    {"s": "https://lp-sachsen.org/resource/522", "field": "jahrgangsstufe", "label": "Klassenstufe 7"},
    {"s": "https://lp-sachsen.org/resource/522", "field": "jahrgangsstufe", "label": "Klassenstufe 6"},
    {
        "s": "https://lehrplan.yovisto.com/resource/lp/be/curriculum/28",
        "field": "schulfach",
        "label": "Physik (KIM-Schulfach)",
    },
]
CLOSURES = {
    "https://lp-sachsen.org/resource/522": [
        {"n": "sn:frag", "label": "Lehrplan", "types": LP + "LP_0002110", "ancestors": ""},
        {
            "n": "sn:lb2",
            "label": "Lernbereich 2: Optik",
            "types": LP + "LP_0002113",
            "ancestors": "sn:frag",
            "jahrgaenge": "Klassenstufe 7|jg7",
        },
        {
            "n": "sn:k1",
            "label": "Lichtbrechung an Linsen",
            "types": LP + "LP_0002115",
            "ancestors": "sn:lb2",
            "position": "1",
        },
        {
            "n": "sn:odd",
            "label": "Ohne Rolle",
            "types": "http://purl.obolibrary.org/obo/BFO_0000001",
            "ancestors": "sn:lb2",
        },
    ],
    "https://lehrplan.yovisto.com/resource/lp/be/curriculum/28": [
        {
            "n": "be:std",
            "label": "Phänomene der Optik beschreiben",
            "types": f"{LP}LP_0000263|{LP}LP_0001447",
            "ancestors": "",
        },
    ],
}
CLASS_ROLES = [
    {"type": LP + "LP_0002110", "typeLabel": "Lehrplanfragment (SN)", "funktion": LP + "LP_0000627"},
    {
        "type": LP + "LP_0002113",
        "typeLabel": "Lernbereich (SN)",
        "funktion": LP + "LP_0000497",
        "ceSuper": LP + "LP_0000349",
    },
    {"type": LP + "LP_0002115", "typeLabel": "Lernziel und Lerninhalt (SN)", "funktion": LP + "LP_0000479"},
    {"type": LP + "LP_0002115", "typeLabel": "Lernziel und Lerninhalt (SN)", "funktion": LP + "LP_0000480"},
]


class FakeEndpoint:
    """Answers the harvest's five query shapes from canned rows and records what was asked."""

    def __init__(self, *, fail_closure: bool = False, counts: dict[str, int] | None = None) -> None:
        self.fail_closure, self.queries = fail_closure, []
        self.counts = counts if counts is not None else {SN.iri: 1, BE.iri: 1}
        self.endpoint = "https://sparql.test/sparql/"

    def select(self, query: str) -> list[dict[str, str]]:
        self.queries.append(query)
        if "COUNT(DISTINCT ?lp)" in query:
            return [{"bl": iri, "n": str(n)} for iri, n in self.counts.items()]
        if "OFFSET" in query:
            if "OFFSET 0" not in query:
                return []
            return next((rows for iri, rows in LISTS.items() if f"<{iri}>" in query), [])
        if "?field" in query:
            return [row for row in HEADS if f"<{row['s']}>" in query]
        if "VALUES ?type" in query:
            return [row for row in CLASS_ROLES if f"<{row['type']}>" in query]
        if "SELECT DISTINCT ?n WHERE" in query:
            if self.fail_closure:
                raise SparqlError("HTTP 500 von https://sparql.test/sparql/: transitive temp memory")
            return next((rows for iri, rows in CLOSURES.items() if f"<{iri}>" in query), [])
        raise AssertionError(f"unexpected query: {query[:200]}")


def _harvest(tmp_path: Path, endpoint: FakeEndpoint, when: datetime = T0) -> LehrplanHarvest:
    return LehrplanHarvest(endpoint, tmp_path / "lehrplan.db", clock=lambda: when)  # type: ignore[arg-type]


def test_run_asks_every_state_and_fills_the_cache_with_roles_parents_and_meta(tmp_path: Path) -> None:
    endpoint = FakeEndpoint()
    report = _harvest(tmp_path, endpoint).run()

    assert sum(1 for q in endpoint.queries if "OFFSET 0" in q) == 16  # coverage grows with MEM, no state list
    assert report.lehrplaene == {"SN": 1, "BE": 1}
    assert report.nodes == 5
    assert report.unknown_classes == {"http://purl.obolibrary.org/obo/BFO_0000001": 1}
    store = LehrplanStore(tmp_path / "lehrplan.db")
    assert store.counts() == {"lehrplaene": {"SN": 1, "BE": 1}, "nodes": 5}
    meta = store.meta()
    assert meta["harvested_at"] == "2026-09-17T12:00:00+00:00"
    assert meta["endpoint"] == "https://sparql.test/sparql/"
    assert meta["ontology_version"] == "1.0.0rc3"
    assert json.loads(meta["counts"]) == {"SN": 1, "BE": 1}
    hits = {hit.iri: hit for hit in store.search(["Optik"])}
    assert hits["sn:k1"].rollen == ["kompetenz", "inhalt"]
    assert hits["sn:k1"].parent_label == "Lernbereich 2: Optik"
    assert hits["sn:lb2"].rollen == ["themenbereich"] and hits["sn:lb2"].jahrgangsstufen == ["Klassenstufe 7"]
    assert hits["be:std"].rollen == ["kompetenz"]
    assert hits["sn:k1"].lehrplan.schulfaecher == ["Physik"]
    assert hits["sn:k1"].lehrplan.jahrgangsstufen == ["Klassenstufe 6", "Klassenstufe 7"]
    assert "sn:frag" not in hits and "sn:odd" not in hits
    status = read_status(tmp_path)
    assert status is not None and status["state"] == "idle" and status["last_run"]["nodes"] == 5


def test_failed_run_keeps_the_previous_cache_and_records_the_error(tmp_path: Path) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    with pytest.raises(SparqlError, match="transitive"):
        _harvest(tmp_path, FakeEndpoint(fail_closure=True), when=T0 + timedelta(days=1)).run()
    assert LehrplanStore(tmp_path / "lehrplan.db").counts()["nodes"] == 5
    assert not (tmp_path / "lehrplan.db.tmp").exists()
    status = read_status(tmp_path)
    assert status is not None and status["state"] == "error" and "transitive" in status["error"]
    assert (tmp_path / STATUS_FILE).exists()


def test_check_compares_endpoint_counts_with_the_last_harvest(tmp_path: Path) -> None:
    harvest = _harvest(tmp_path, FakeEndpoint())
    assert harvest.check()["changed"] is True  # nothing harvested yet
    harvest.run()
    unchanged = harvest.check()
    assert unchanged == {"changed": False, "remote": {"SN": 1, "BE": 1}, "local": {"SN": 1, "BE": 1}}
    grown = _harvest(tmp_path, FakeEndpoint(counts={SN.iri: 2, BE.iri: 1})).check()
    assert grown["changed"] is True and grown["remote"] == {"SN": 2, "BE": 1}


def test_due_when_missing_stale_or_changed(tmp_path: Path) -> None:
    harvest = _harvest(tmp_path, FakeEndpoint())
    assert harvest.due(max_age=timedelta(days=30)) is True
    harvest.run()
    assert _harvest(tmp_path, FakeEndpoint(), when=T0 + timedelta(days=7)).due(max_age=timedelta(days=30)) is False
    assert _harvest(tmp_path, FakeEndpoint(), when=T0 + timedelta(days=31)).due(max_age=timedelta(days=30)) is True
    changed = _harvest(tmp_path, FakeEndpoint(counts={SN.iri: 3}), when=T0 + timedelta(days=7))
    assert changed.due(max_age=timedelta(days=30)) is True


def test_a_second_harvest_is_refused_while_the_lock_is_held_and_a_stale_lock_is_ignored(tmp_path: Path) -> None:
    from app.sources.lehrplan.harvest import LOCK_FILE, LOCK_STALE_S, HarvestRunningError

    lock = tmp_path / LOCK_FILE
    lock.write_text("pid 1\n", encoding="utf-8")
    with pytest.raises(HarvestRunningError):
        _harvest(tmp_path, FakeEndpoint()).run()
    assert not (tmp_path / "lehrplan.db").exists()
    assert lock.exists()  # a foreign lock is never removed
    import os

    stale = T0.timestamp() - LOCK_STALE_S - 1
    os.utime(lock, (stale, stale))
    report = _harvest(tmp_path, FakeEndpoint(), when=T0).run()
    assert report.nodes == 5
    assert not lock.exists()  # released after the run


def test_an_interrupt_records_the_error_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    class Interrupting(FakeEndpoint):
        def select(self, query: str) -> list[dict[str, str]]:
            if "SELECT DISTINCT ?n WHERE" in query:
                raise KeyboardInterrupt
            return super().select(query)

    with pytest.raises(KeyboardInterrupt):
        _harvest(tmp_path, Interrupting()).run()
    status = read_status(tmp_path)
    assert status is not None and status["state"] == "error" and "KeyboardInterrupt" in status["error"]
    assert not (tmp_path / "lehrplan.db.tmp").exists()


def test_an_invalid_iri_from_the_endpoint_skips_that_curriculum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        LISTS, SN.iri, [*LISTS[SN.iri], {"s": "https://lp-sachsen.org/res ource/bad", "label": "Kaputt"}]
    )
    report = _harvest(tmp_path, FakeEndpoint()).run()
    assert report.lehrplaene == {"SN": 1, "BE": 1}
    assert report.skipped == ["https://lp-sachsen.org/res ource/bad"]


def test_html_entities_in_labels_are_unescaped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MEM carries labels such as "Physik&nbsp;13"; the cache stores plain text with plain spaces."""
    monkeypatch.setitem(LISTS, SN.iri, [{"s": "https://lp-sachsen.org/resource/522", "label": "Gymnasium&nbsp;Physik"}])
    monkeypatch.setitem(
        CLOSURES,
        "https://lp-sachsen.org/resource/522",
        [
            {"n": "sn:lb2", "label": "Lernbereich 2: Optik", "types": LP + "LP_0002113", "ancestors": ""},
            {
                "n": "sn:k1",
                "label": "Licht&nbsp;und Schatten &amp; Farben",
                "types": LP + "LP_0002115",
                "ancestors": "sn:lb2",
            },
        ],
    )
    _harvest(tmp_path, FakeEndpoint()).run()
    hits = {hit.iri: hit for hit in LehrplanStore(tmp_path / "lehrplan.db").search(["Optik"])}
    assert hits["sn:k1"].label == "Licht und Schatten & Farben"
    assert hits["sn:k1"].lehrplan.label == "Gymnasium Physik"
