"""CLI: ``compendium lehrplan status`` and ``lehrplan search`` against a temporary state directory."""

import json
import logging
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.cli import main
from app.cli_lehrplan import loop_task
from app.settings import get_settings
from app.sources.lehrplan.harvest import HarvestRunningError
from app.sources.lehrplan.sparql import SparqlError, SparqlRefusedError
from tests.conftest import ROOT
from tests.test_lehrplan_api import write_broken_cache, write_cache


@pytest.fixture
def state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    state = tmp_path / "state"
    env = {
        "STATE_DIR": str(state),
        "CONFIG_DIR": str(ROOT / "config"),
        "ZIM_DIR": str(tmp_path / "zim"),
        "ZIM_PATHS": "",
        "ZIM_REQUIRED": "",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield state
    get_settings.cache_clear()


def test_status_reports_missing_and_then_present_cache(state_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lehrplan", "status"]) == 0
    assert "kein Lehrplan-Cache vorhanden" in capsys.readouterr().out
    write_cache(state_dir)
    assert main(["lehrplan", "status"]) == 0
    out = capsys.readouterr().out
    assert "Stand 2026-09-17" in out and "SN: 1" in out


def test_status_names_a_failed_check(state_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_cache(state_dir)
    failure = "SparqlError: MEM-Endpunkt https://sparql.test/sparql/ nicht erreichbar"
    status = {"state": "idle", "check_error": failure}
    (state_dir / "lehrplan_status.json").write_text(json.dumps(status), encoding="utf-8")

    assert main(["lehrplan", "status"]) == 0

    assert f"Letzte Prüfung gescheitert: {failure}" in capsys.readouterr().out


def test_search_prints_matches_and_respects_the_subject(state_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lehrplan", "search", "--q", "Optik"]) == 1  # no cache yet
    write_cache(state_dir)
    assert main(["lehrplan", "search", "--q", "Optik", "--subject", "Physik"]) == 0
    out = capsys.readouterr().out
    assert "1 Treffer" in out and "Lichtbrechung an Linsen" in out and "[SN]" in out
    assert main(["lehrplan", "search", "--q", "Optik", "--subject", "Chemie"]) == 0
    assert capsys.readouterr().out.startswith("0 Treffer")


def test_search_on_a_cache_without_its_tables_says_so(state_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_broken_cache(state_dir)  # the schema check passes, the node tables are missing
    assert main(["lehrplan", "search", "--q", "Optik"]) == 1  # a traceback before
    assert "nicht lesbar" in capsys.readouterr().err


def test_the_harvest_loop_stops_cleanly_on_sigterm(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[object] = []
    monkeypatch.setattr("app.cli_lehrplan.stop_on_sigterm", lambda: installed.append("sigterm"))

    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt  # what SIGTERM becomes

    monkeypatch.setattr("app.cli_lehrplan.run_periodically", interrupted)
    assert main(["lehrplan", "harvest", "--loop"]) == 0  # a stopped container, not a traceback
    assert installed == ["sigterm"]


def test_a_failed_harvest_is_retried_within_the_hour(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without retry_after a MEM failure waited the whole LEHRPLAN_CHECK_INTERVAL of seven days, also on the first
    start with no cache; the ZIM loop retries after an hour (review of 2026-09-25)."""
    seen: dict[str, object] = {}
    monkeypatch.setattr("app.cli_lehrplan.stop_on_sigterm", lambda: None)

    def record(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr("app.cli_lehrplan.run_periodically", record)
    assert main(["lehrplan", "harvest", "--loop"]) == 0
    assert seen["retry_after"] == timedelta(hours=1)


class FakeHarvest:
    """Stands in for the harvest the CLI builds; records how each run was asked for."""

    def __init__(self, *, due: bool = False, refuse: bool = False, error: Exception | None = None) -> None:
        self.is_due, self.refuse, self.error = due, refuse, error
        self.forced: list[bool] = []

    def due(self, *, max_age: object) -> bool:
        return self.is_due

    def check(self) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return {"changed": True, "remote": {"SN": 2}, "local": {"SN": 1}}

    def run(self, *, force: bool = False) -> object:
        from app.sources.lehrplan.harvest import HarvestRefusedError, HarvestReport

        self.forced.append(force)
        if self.error is not None:
            raise self.error
        if self.refuse and not force:
            raise HarvestRefusedError("MEM listet keinen Lehrplan; der bisherige Cache bleibt")
        return HarvestReport(started_at="2026-09-27T00:00:00+00:00", finished_at="2026-09-27T00:15:00+00:00")


def test_force_reaches_the_harvest(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--force also takes a result the harvest would refuse as a loss (audit 2026-09-27, KO-01)."""
    fake = FakeHarvest()
    monkeypatch.setattr("app.cli_lehrplan._harvest", lambda settings: fake)

    assert main(["lehrplan", "harvest", "--force"]) == 0
    assert main(["lehrplan", "harvest"]) == 0  # not due: no run

    assert fake.forced == [True]


def test_a_refused_harvest_ends_with_a_message_instead_of_a_traceback(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("app.cli_lehrplan._harvest", lambda settings: FakeHarvest(due=True, refuse=True))

    assert main(["lehrplan", "harvest"]) == 1
    assert "Harvest verworfen: MEM listet keinen Lehrplan" in capsys.readouterr().err


def test_the_harvest_loop_signs_life_into_the_state_directory(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.jobs.runner import last_alive
    from app.sources.lehrplan.harvest import ALIVE_FILE

    seen: dict[str, Any] = {}
    monkeypatch.setattr("app.cli_lehrplan.stop_on_sigterm", lambda: None)
    monkeypatch.setattr("app.cli_lehrplan.run_periodically", lambda *args, **kwargs: seen.update(kwargs))
    assert main(["lehrplan", "harvest", "--loop"]) == 0

    seen["alive"]()

    assert last_alive(state_dir / ALIVE_FILE) is not None  # what the API reports (kompendium_lehrplan_harvest_...)


def test_status_tells_an_unusable_cache_from_a_missing_one(state_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state_dir.mkdir(parents=True)
    (state_dir / "lehrplan.db").write_bytes(b"keine SQLite-Datei")

    assert main(["lehrplan", "status"]) == 0

    assert "Lehrplan-Cache unbrauchbar" in capsys.readouterr().out


def test_status_names_the_error_and_the_progress_of_a_running_harvest(
    state_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_cache(state_dir)
    progress = {"state": "SN", "lehrplaene_done": 3, "of": 16, "nodes": 1200}
    status = {
        "state": "running",
        "updated_at": "2026-10-08T09:00:00Z",
        "error": "MEM antwortete 502",
        "progress": progress,
    }
    (state_dir / "lehrplan_status.json").write_text(json.dumps(status), encoding="utf-8")

    assert main(["lehrplan", "status"]) == 0

    out = capsys.readouterr().out
    assert "Letzter Harvest-Lauf: running (2026-10-08T09:00:00Z)" in out
    assert "  Fehler: MEM antwortete 502" in out and f"  Fortschritt: {progress}" in out


def test_check_prints_the_counts_of_mem_beside_those_of_the_cache(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("app.cli_lehrplan._harvest", lambda settings: FakeHarvest())

    assert main(["lehrplan", "check"]) == 0

    assert json.loads(capsys.readouterr().out) == {"changed": True, "remote": {"SN": 2}, "local": {"SN": 1}}


def test_check_says_when_mem_is_unreachable(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unreachable = SparqlError("https://sparql.test/sparql/ antwortet nicht")
    monkeypatch.setattr("app.cli_lehrplan._harvest", lambda settings: FakeHarvest(error=unreachable))

    assert main(["lehrplan", "check"]) == 1

    assert "MEM nicht erreichbar: https://sparql.test/sparql/ antwortet nicht" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (HarvestRunningError("ein anderer Harvest hält lehrplan.lock"), "ein anderer Harvest hält lehrplan.lock"),
        (SparqlError("MEM antwortet nicht"), "Harvest abgebrochen, alter Cache bleibt: MEM antwortet nicht"),
    ],
)
def test_a_harvest_that_cannot_run_ends_with_a_message(
    state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    message: str,
) -> None:
    monkeypatch.setattr("app.cli_lehrplan._harvest", lambda settings: FakeHarvest(due=True, error=error))

    assert main(["lehrplan", "harvest"]) == 1

    assert message in capsys.readouterr().err


def test_the_loop_forces_its_first_run_only_and_waits_out_a_refusal(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.cli_lehrplan")
    fake = FakeHarvest(due=True, refuse=True)
    task = loop_task(fake, max_age=timedelta(days=30), force=True)  # type: ignore[arg-type]

    assert task() is None  # forced: the result is taken although the harvest would refuse it
    assert task() is True  # refused: the next try is the next check, not the early retry
    assert fake.forced == [True, False]
    [refused] = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert refused.getMessage().startswith("Harvest verworfen, nächster Versuch mit der nächsten Prüfung")


def test_the_loop_waits_out_a_refused_query_and_leaves_an_unreachable_mem_to_the_early_retry() -> None:
    refused = FakeHarvest(due=True, error=SparqlRefusedError("HTTP 400"))
    unreachable = FakeHarvest(due=True, error=SparqlError("nicht erreichbar"))

    assert loop_task(refused, max_age=timedelta(days=30), force=False)() is True  # type: ignore[arg-type]
    with pytest.raises(SparqlError, match="nicht erreichbar"):  # run_periodically retries a raising task early
        loop_task(unreachable, max_age=timedelta(days=30), force=False)()  # type: ignore[arg-type]


def test_search_writes_its_matches_as_json(state_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_cache(state_dir)
    out_file = tmp_path / "treffer.json"

    assert main(["lehrplan", "search", "--q", "Optik", "--json", str(out_file)]) == 0

    [entry] = json.loads(out_file.read_text(encoding="utf-8"))
    assert entry["label"] == "Lichtbrechung an Linsen" and entry["bundesland_code"] == "SN"
    assert f"JSON geschrieben: {out_file}" in capsys.readouterr().out


def test_a_loop_run_reports_in_one_log_record(caplog: pytest.LogCaptureFixture) -> None:
    """As the updater a report or "current" is a log record of one line, so LOG_FORMAT=json makes it one JSON
    object; printed, the report spread over many lines (review of 2026-10-08)."""
    caplog.set_level(logging.INFO, logger="app.cli_lehrplan")

    assert loop_task(FakeHarvest(due=True), max_age=timedelta(days=30), force=False)() is None  # type: ignore[arg-type]
    assert loop_task(FakeHarvest(due=False), max_age=timedelta(days=30), force=False)() is None  # type: ignore[arg-type]

    report, current = [record.getMessage() for record in caplog.records if record.name == "app.cli_lehrplan"]
    assert report.startswith("Harvest-Bericht: {") and "2026-09-27T00:15:00+00:00" in report
    assert current.startswith("Lehrplan-Cache ist aktuell") and not any("\n" in text for text in (report, current))
