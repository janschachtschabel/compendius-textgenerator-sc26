"""CLI: ``compendium lehrplan status`` and ``lehrplan search`` against a temporary state directory."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.cli import main
from app.settings import get_settings
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
    from datetime import timedelta

    seen: dict[str, object] = {}
    monkeypatch.setattr("app.cli_lehrplan.stop_on_sigterm", lambda: None)

    def record(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr("app.cli_lehrplan.run_periodically", record)
    assert main(["lehrplan", "harvest", "--loop"]) == 0
    assert seen["retry_after"] == timedelta(hours=1)


class FakeHarvest:
    """Stands in for the harvest the CLI builds; records how each run was asked for."""

    def __init__(self, *, due: bool = False, refuse: bool = False) -> None:
        self.is_due, self.refuse = due, refuse
        self.forced: list[bool] = []

    def due(self, *, max_age: object) -> bool:
        return self.is_due

    def run(self, *, force: bool = False) -> object:
        from app.sources.lehrplan.harvest import HarvestRefusedError, HarvestReport

        self.forced.append(force)
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
