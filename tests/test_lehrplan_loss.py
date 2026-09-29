"""A harvest that would lose curricula or their elements keeps the cache and says so, without pulling MEM every hour
(audit 2026-09-28, KO-20, BE-11 and DB-02; audit 2026-09-29, Q1).

KO-01 refused a harvest that lost a state, but only after the whole run - about 2,600 SPARQL queries in 25 minutes -
and as an error the loop retried after an hour: while MEM listed less, the harvest pulled it 17 times a day, and the
alert saw the error only in the second after it. Empty answers to the element queries went unseen and emptied the
curricula they came for. A crash right after the swap could leave a cache with broken pages that no check noticed.
Empty answers about the roles of the element classes or the head fields of the curricula were taken as well: the
elements lost the roles a search looks for, the curricula their subjects, and the run replaced the cache.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.cli_lehrplan import loop_task
from app.jobs.runner import run_periodically
from app.sources.lehrplan.harvest import LOCK_FILE, STATUS_FILE, HarvestRefusedError, read_status
from app.sources.lehrplan.sparql import SparqlError, SparqlRefusedError
from app.sources.lehrplan.store import LehrplanStore
from tests.test_lehrplan_harvest import BE, CLOSURES, LISTS, LP, SN, T0, FakeEndpoint, _harvest
from tests.test_metrics import _app, scrape, value
from tests.test_runner import FakeClock

SAXONY = "https://lp-sachsen.org/resource/522"  # four elements in the fake endpoint, Berlin's curriculum one
ELEMENTS = "SELECT DISTINCT ?n WHERE"
ROLES = "VALUES ?type"  # the query about the element classes
HEADS = "?field"  # the query about the head fields of a block of curricula
SAXON_CLASS = f"<{LP}LP_0002115>"  # a Saxon element class; its roles come from the ontology alone


def test_a_loss_the_counts_show_is_refused_before_anything_is_pulled(tmp_path: Path) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    endpoint = FakeEndpoint(counts={BE.iri: 1})  # MEM counts no curriculum of Saxony, as while it reloads a graph

    with pytest.raises(HarvestRefusedError, match="SN"):
        _harvest(tmp_path, endpoint, when=T0 + timedelta(days=1)).run()

    assert len(endpoint.queries) == 1 and "COUNT(DISTINCT ?lp)" in endpoint.queries[0]


class ReloadingEndpoint(FakeEndpoint):
    """Answers the queries that hold every one of ``marks`` - the element query of Saxony's curriculum unless said
    otherwise - with no rows the first ``empty`` times, as Virtuoso does while it reloads a graph."""

    def __init__(self, empty: int, marks: tuple[str, ...] = (ELEMENTS, f"<{SAXONY}>")) -> None:
        super().__init__()
        self.empty, self.marks = empty, marks

    def select(self, query: str) -> list[dict[str, str]]:
        if all(mark in query for mark in self.marks) and self.empty > 0:
            self.queries.append(query)
            self.empty -= 1
            return []
        return super().select(query)


def test_an_empty_answer_for_a_curriculum_that_had_elements_is_asked_again(tmp_path: Path) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    endpoint = ReloadingEndpoint(empty=1)

    report = _harvest(tmp_path, endpoint, when=T0 + timedelta(days=1)).run()

    assert len([query for query in endpoint.queries if ELEMENTS in query and f"<{SAXONY}>" in query]) == 2
    assert report.nodes == 5 and report.emptied == []


def test_a_run_that_empties_the_elements_of_a_state_keeps_the_cache(tmp_path: Path) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()

    with pytest.raises(HarvestRefusedError, match="SN"):
        _harvest(tmp_path, ReloadingEndpoint(empty=2), when=T0 + timedelta(days=1)).run()

    assert LehrplanStore(tmp_path / "lehrplan.db").counts()["nodes"] == 5


def test_the_elements_per_state_are_kept_with_the_cache(tmp_path: Path) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()

    assert json.loads(LehrplanStore(tmp_path / "lehrplan.db").meta()["nodes_per_state"]) == {"SN": 4, "BE": 1}


def _findable(tmp_path: Path) -> dict[str, tuple[list[str], list[str]]]:
    """Roles and subjects of the elements a search for "Optik" finds - only elements with a role the matcher weighs."""
    hits = LehrplanStore(tmp_path / "lehrplan.db").search(["Optik"])
    return {hit.iri: (hit.rollen, hit.lehrplan.schulfaecher) for hit in hits}


@pytest.mark.parametrize("marks", [(ROLES, SAXON_CLASS), (HEADS, f"<{SAXONY}>")], ids=["roles", "heads"])
def test_an_empty_answer_about_roles_or_heads_is_asked_again(tmp_path: Path, marks: tuple[str, ...]) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    before = _findable(tmp_path)
    endpoint = ReloadingEndpoint(empty=1, marks=marks)

    _harvest(tmp_path, endpoint, when=T0 + timedelta(days=1)).run()

    assert len([query for query in endpoint.queries if all(mark in query for mark in marks)]) == 2
    assert _findable(tmp_path) == before


@pytest.mark.parametrize(
    ("marks", "message"),
    [((ROLES, SAXON_CLASS), "Rollen"), ((HEADS, f"<{SAXONY}>"), "Kopfdaten")],
    ids=["roles", "heads"],
)
def test_a_run_whose_roles_or_heads_come_back_empty_twice_keeps_the_cache(
    tmp_path: Path, marks: tuple[str, ...], message: str
) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    before = _findable(tmp_path)

    with pytest.raises(HarvestRefusedError, match=message):
        _harvest(tmp_path, ReloadingEndpoint(empty=2, marks=marks), when=T0 + timedelta(days=1)).run()

    assert before == {
        "be:std": (["kompetenz"], ["Physik"]),
        "sn:lb2": (["themenbereich"], ["Physik"]),
        "sn:k1": (["kompetenz", "inhalt"], ["Physik"]),
    }
    assert _findable(tmp_path) == before


def test_curricula_without_head_fields_in_the_cache_may_answer_none(tmp_path: Path) -> None:
    endpoint = ReloadingEndpoint(empty=99, marks=(HEADS,))

    report = _harvest(tmp_path, endpoint).run()

    # a curriculum may name no head field with a label; nothing in a first run says these had one
    assert report.nodes == 5
    assert len([query for query in endpoint.queries if HEADS in query]) == 2  # one per state, none asked again


def test_a_forced_run_takes_an_empty_answer_and_asks_for_those_classes_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second = "https://lp-sachsen.org/resource/523"
    monkeypatch.setitem(LISTS, SN.iri, [*LISTS[SN.iri], {"s": second, "label": "Gymnasium Physik 8"}])
    element = {"n": "sn:k2", "label": "Optik im Alltag", "types": LP + "LP_0002115", "ancestors": ""}
    monkeypatch.setitem(CLOSURES, second, [element])

    _harvest(tmp_path, ReloadingEndpoint(empty=2, marks=(ROLES, SAXON_CLASS))).run(force=True)

    # the first Saxon curriculum keeps its elements without roles; the second asks for its class again and has them
    assert set(_findable(tmp_path)) == {"be:std", "sn:k2"}


def test_a_run_that_leaves_a_state_less_than_half_its_findable_elements_keeps_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    before = _findable(tmp_path)
    # while the ontology graph is gone, the class query still answers a row per class, but without any role
    monkeypatch.setattr("tests.test_lehrplan_harvest.CLASS_ROLES", [])

    with pytest.raises(HarvestRefusedError, match="SN 0 statt 2"):
        _harvest(tmp_path, FakeEndpoint(), when=T0 + timedelta(days=1)).run()

    assert _findable(tmp_path) == before


@pytest.mark.parametrize(
    ("failure", "runs"),
    [
        (HarvestRefusedError("MEM listet deutlich weniger Lehrpläne als der Cache hält"), 1),
        (SparqlRefusedError("HTTP 500 von https://sparql.test/sparql/: transitive temp memory"), 1),
        (SparqlError("MEM-Endpunkt https://sparql.test/sparql/ nicht erreichbar"), 24),  # this one a retry may help
    ],
)
def test_a_harvest_a_retry_cannot_help_waits_for_the_next_check(failure: Exception, runs: int) -> None:
    clock, stop, started = FakeClock(), threading.Event(), []
    end = clock.now + 24 * 3600 - 1

    class Failing:
        def due(self, *, max_age: timedelta) -> bool:
            return True

        def run(self, *, force: bool = False) -> Any:
            started.append(clock.now)
            raise failure

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now >= end:
            stop.set()

    task = loop_task(Failing(), max_age=timedelta(days=30), force=False)  # type: ignore[arg-type]
    run_periodically(
        task, timedelta(days=7), retry_after=timedelta(hours=1), poll_s=60, stop=stop, clock=clock, sleep=sleep
    )

    assert len(started) == runs  # a day: one run, not 17 full pulls of MEM


class PeekingEndpoint(FakeEndpoint):
    """Reads the status file when the run lists its first state."""

    def __init__(self, state_dir: Path) -> None:
        super().__init__()
        self.state_dir = state_dir
        self.seen: dict[str, Any] | None = None

    def select(self, query: str) -> list[dict[str, str]]:
        if "OFFSET 0" in query and self.seen is None:
            self.seen = read_status(self.state_dir)
        return super().select(query)


def test_a_failed_harvest_stays_failed_until_one_succeeds(tmp_path: Path) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    with pytest.raises(HarvestRefusedError):
        _harvest(tmp_path, FakeEndpoint(counts={BE.iri: 1}), when=T0 + timedelta(days=1)).run()
    peeking = PeekingEndpoint(tmp_path)

    _harvest(tmp_path, peeking, when=T0 + timedelta(days=2)).run()

    assert peeking.seen is not None and peeking.seen["state"] == "running"
    assert "HarvestRefusedError" in peeking.seen["last_error"]  # while the next run runs, for the alert
    status = read_status(tmp_path)
    assert status is not None and status["last_error"] is None


def test_the_gauge_reads_the_last_finished_harvest(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / STATUS_FILE).write_text(
        json.dumps({"state": "running", "last_error": "HarvestRefusedError: MEM listet weniger"}), encoding="utf-8"
    )

    with _app(sample_zims, tmp_path) as client:
        assert value(scrape(client), "kompendium_lehrplan_harvest_failed") == 1


class UnreachableEndpoint(FakeEndpoint):
    """MEM out of reach: every query fails as the client reports it after its retries."""

    def select(self, query: str) -> list[dict[str, str]]:
        self.queries.append(query)
        raise SparqlError("MEM-Endpunkt https://sparql.test/sparql/ nicht erreichbar: ConnectError")


def test_a_failed_check_shows_until_a_check_succeeds(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """Four weeks of an unreachable MEM left the status and the gauge untouched: the weekly check raised before any run
    (audit 2026-09-29, Q3)."""
    state = tmp_path / "state"
    state.mkdir()
    _harvest(state, FakeEndpoint()).run()
    week = T0 + timedelta(days=7)

    with pytest.raises(SparqlError):
        _harvest(state, UnreachableEndpoint(), when=week).due(max_age=timedelta(days=30))

    with _app(sample_zims, tmp_path) as client:
        assert value(scrape(client), "kompendium_lehrplan_harvest_failed") == 1
    status = read_status(state)
    assert status is not None and "nicht erreichbar" in status["check_error"]
    assert status["state"] == "idle" and status["last_run"]["nodes"] == 5  # the last harvest stays as it was
    assert _harvest(state, FakeEndpoint(), when=week + timedelta(hours=1)).due(max_age=timedelta(days=30)) is False
    status = read_status(state)
    assert status is not None and status["check_error"] is None
    with _app(sample_zims, tmp_path) as client:
        assert value(scrape(client), "kompendium_lehrplan_harvest_failed") == 0


def test_a_good_check_leaves_the_error_of_a_failed_run(tmp_path: Path) -> None:
    # only a run that succeeds clears it: the next run would otherwise start with the gauge at 0 (audit BE-11)
    _harvest(tmp_path, FakeEndpoint()).run()
    with pytest.raises(HarvestRefusedError):
        _harvest(tmp_path, FakeEndpoint(counts={BE.iri: 1}), when=T0 + timedelta(days=1)).run()

    assert _harvest(tmp_path, FakeEndpoint(counts={BE.iri: 1}), when=T0 + timedelta(days=8)).due(
        max_age=timedelta(days=30)
    )

    status = read_status(tmp_path)
    assert status is not None and "HarvestRefusedError" in status["last_error"]


def test_a_check_writes_nothing_while_a_harvest_runs(tmp_path: Path) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    before = (tmp_path / STATUS_FILE).read_text(encoding="utf-8")
    (tmp_path / LOCK_FILE).write_text("pid 1\n", encoding="utf-8")  # the run writes its own outcome

    with pytest.raises(SparqlError):
        _harvest(tmp_path, UnreachableEndpoint(), when=T0 + timedelta(days=7)).due(max_age=timedelta(days=30))

    assert (tmp_path / STATUS_FILE).read_text(encoding="utf-8") == before


def test_a_check_it_cannot_record_still_ends_as_it_did(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()

    def read_only(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError("read-only file system")

    monkeypatch.setattr("app.sources.lehrplan.harvest.acquire_lock", read_only)

    with pytest.raises(SparqlError, match="nicht erreichbar"):
        _harvest(tmp_path, UnreachableEndpoint(), when=T0 + timedelta(days=7)).due(max_age=timedelta(days=30))


def test_the_cache_is_on_disk_before_it_replaces_the_old_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str]] = []
    replace = os.replace
    monkeypatch.setattr("app.sources.lehrplan.store.to_disk", lambda path: events.append(("to_disk", path.name)))

    def recorded_replace(source: Any, target: Any) -> None:
        events.append(("replace", Path(source).name))
        replace(source, target)

    monkeypatch.setattr("app.sources.lehrplan.store.os.replace", recorded_replace)

    _harvest(tmp_path, FakeEndpoint()).run()

    # os.replace is the module's everywhere: the status file is swapped in the same way
    cache = [event for event in events if event[1].startswith("lehrplan.db")]
    assert cache == [("to_disk", "lehrplan.db.tmp"), ("replace", "lehrplan.db.tmp")]


def test_a_cache_with_broken_pages_is_due_for_a_new_harvest(tmp_path: Path) -> None:
    _harvest(tmp_path, FakeEndpoint()).run()
    path = tmp_path / "lehrplan.db"
    data = bytearray(path.read_bytes())
    data[-4096:] = b"\xff" * 4096  # the last page, as a crash right after the swap may leave it
    path.write_bytes(bytes(data))

    assert LehrplanStore(path).available  # its meta rows still read
    assert _harvest(tmp_path, FakeEndpoint(), when=T0 + timedelta(hours=1)).due(max_age=timedelta(days=30))
