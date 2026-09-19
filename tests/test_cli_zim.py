"""CLI: ``compendium zim sync --offline`` and ``zim status`` against a temporary ZIM directory."""

import shutil
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.cli import main
from app.settings import get_settings
from app.sources.zim.active import read_active

MANIFEST_YAML = """version: 1
profiles: {compact: test}
subscriptions:
  - {id: wikipedia_de_sample, name: wikipedia_de_sample, project: wikipedia, required: true, profiles: [compact]}
  - {id: klexikon_de_sample, name: klexikon_de_sample, project: klexikon, required: true, profiles: [compact]}
"""


@pytest.fixture
def zim_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_zims: dict[str, Path]) -> Iterator[Path]:
    zim_dir = tmp_path / "zim"
    zim_dir.mkdir()
    shutil.copy(sample_zims["klexikon"], zim_dir / "klexikon_de_sample_2026-08.zim")
    config = tmp_path / "config"
    config.mkdir()
    (config / "zim_subscriptions.yaml").write_text(MANIFEST_YAML, encoding="utf-8")
    env = {
        "ZIM_DIR": str(zim_dir),
        "CONFIG_DIR": str(config),
        "STATE_DIR": str(tmp_path / "state"),
        "ZIM_PROFILE": "compact",
        "ZIM_REQUIRED": "",
        "ZIM_PATHS": "",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield zim_dir
    get_settings.cache_clear()


def test_zim_sync_offline_adopts_and_status_reports(zim_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["zim", "sync", "--offline"]) == 0
    state = read_active(zim_env)
    assert state is not None
    assert state.archives["klexikon_de_sample"].file == "klexikon_de_sample_2026-08.zim"
    report = capsys.readouterr().out
    assert '"adopted"' in report
    assert "klexikon_de_sample" in report

    assert main(["zim", "status"]) == 0
    status = capsys.readouterr().out
    assert "klexikon_de_sample_2026-08.zim" in status
    assert "wikipedia_de_sample" in status  # listed as missing required archive


def test_the_sync_loop_retries_a_failed_run_after_an_hour(zim_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def loop(task: Any, interval: timedelta, **kwargs: Any) -> None:
        captured.update(kwargs, interval=interval)

    monkeypatch.setattr("app.cli_zim.run_periodically", loop)
    assert main(["zim", "sync", "--offline", "--loop"]) == 0
    # A run that aborts (full volume, crash) is not left alone for the 30 days of ZIM_SYNC_INTERVAL
    assert captured["interval"] == timedelta(days=30) and captured["retry_after"] == timedelta(hours=1)


def test_a_manual_sync_while_the_updater_runs_says_so(zim_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (zim_env / "sync.lock").write_text("pid 1\n", encoding="utf-8")
    assert main(["zim", "sync", "--offline"]) == 1
    assert "läuft bereits" in capsys.readouterr().err


def test_one_loop_run_asks_for_an_early_retry_when_its_report_says_so() -> None:
    from app.cli_zim import _run_once
    from app.jobs.zim_sync import SyncOptions, SyncReport

    class OneRun:
        def __init__(self, report: SyncReport) -> None:
            self.report = report

        def run(self, options: SyncOptions) -> SyncReport:
            return self.report

    options = SyncOptions(profile="compact")
    assert _run_once(OneRun(SyncReport("compact", "t0", retry_soon=True)), options) is False  # type: ignore[arg-type]
    assert _run_once(OneRun(SyncReport("compact", "t0", errors=["x: SHA-256 mismatch"])), options) is True  # type: ignore[arg-type]


def test_the_sync_loop_stops_cleanly_on_sigterm(zim_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[object] = []
    monkeypatch.setattr("app.cli_zim.stop_on_sigterm", lambda: installed.append("sigterm"))
    monkeypatch.setattr("app.cli_zim.run_periodically", lambda *args, **kwargs: None)
    assert main(["zim", "sync", "--offline", "--loop"]) == 0
    assert installed == ["sigterm"]
