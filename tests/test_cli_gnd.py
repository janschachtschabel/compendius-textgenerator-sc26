"""``compendium gnd sync|build|status``: the GND index of /entities, from the DNB's dumps (D65)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.cli import main
from app.jobs.runner import last_alive
from app.settings import Settings, get_settings
from app.sources.gnd.index import GndIndex
from app.sources.gnd.sync import ALIVE_FILE, LOCK_FILE, GndSync
from tests.conftest import ROOT
from tests.test_gnd_index import write_dumps
from tests.test_gnd_sync import DNB, FakeDnb


@pytest.fixture
def state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    state = tmp_path / "state"
    env = {"STATE_DIR": str(state), "CONFIG_DIR": str(ROOT / "config"), "ZIM_PATHS": "", "ZIM_REQUIRED": ""}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield state
    get_settings.cache_clear()


def _fake_sync(monkeypatch: pytest.MonkeyPatch, dnb: FakeDnb) -> None:
    def build(settings: Settings) -> GndSync:
        client = httpx.Client(transport=httpx.MockTransport(dnb.handler))
        return GndSync(settings.gnd_db_path, client=client, base_url=DNB)

    monkeypatch.setattr("app.cli_gnd.build_gnd_sync", build)


def test_status_before_and_after_a_sync(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["gnd", "status"]) == 0
    assert "kein GND-Index" in capsys.readouterr().out
    dnb = FakeDnb(tmp_path / "dnb")
    dnb.add("20260217")
    _fake_sync(monkeypatch, dnb)
    assert main(["gnd", "sync"]) == 0
    assert "kein Index vorhanden" in capsys.readouterr().out
    assert main(["gnd", "status"]) == 0
    out = capsys.readouterr().out
    assert "8 Datensätze" in out and "Release 2026-02-17" in out
    assert main(["gnd", "sync"]) == 0
    assert "aktuell" in capsys.readouterr().out and len(dnb.downloads()) == 2


def test_a_build_by_hand_from_the_dumps_on_disk(state_dir: Path, tmp_path: Path) -> None:
    (subjects, _), (places, _) = write_dumps(tmp_path / "dumps")
    assert main(["gnd", "build", "--sachbegriff", str(subjects), "--geografikum", str(places)]) == 0
    hit = GndIndex(state_dir / "gnd.db").find("Berlin", qid="Q64")
    assert hit is not None and hit.kind == "Geografikum"


def test_a_build_by_hand_does_not_start_while_the_sync_runs(
    state_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / LOCK_FILE).write_text("pid 1", encoding="utf-8")
    (subjects, _), (places, _) = write_dumps(tmp_path / "dumps")
    assert main(["gnd", "build", "--sachbegriff", str(subjects), "--geografikum", str(places)]) == 1
    assert "läuft" in capsys.readouterr().err


def test_the_sync_loop_checks_at_the_interval_of_the_settings(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dnb = FakeDnb(tmp_path / "dnb")
    dnb.add("20260217")
    _fake_sync(monkeypatch, dnb)
    seen: dict[str, object] = {}

    def once(task: Callable[[], object], interval: timedelta, **options: object) -> None:
        seen.update(interval=interval, **options)
        task()

    monkeypatch.setattr("app.cli_sync.run_periodically", once)
    monkeypatch.setattr("app.cli_sync.stop_on_sigterm", lambda: None)
    assert main(["gnd", "sync", "--loop"]) == 0
    assert seen["interval"] == timedelta(days=1) and (state_dir / "gnd.db").exists()


def test_the_sync_loop_signs_life_into_the_state_directory(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr("app.cli_sync.stop_on_sigterm", lambda: None)
    monkeypatch.setattr("app.cli_sync.run_periodically", lambda *args, **kwargs: seen.update(kwargs))
    assert main(["gnd", "sync", "--loop"]) == 0

    seen["alive"]()

    assert last_alive(state_dir / ALIVE_FILE) is not None  # what the API reports (kompendium_gnd_sync_alive_...)
