"""CLI: ``compendium zim sync --offline`` and ``zim status`` against a temporary ZIM directory."""

import json
import shutil
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.cli import main
from app.jobs.runner import last_alive
from app.jobs.zim_sync import ALIVE_FILE, STATUS_FILE
from app.settings import get_settings
from app.sources.zim.active import RetiredArchive, read_active, write_active
from app.sources.zim.catalog import KiwixCatalog

OPDS = Path(__file__).parent / "fixtures" / "opds"

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

        def due_in(self, report: SyncReport) -> None:
            return None  # no retired archive waits

    options = SyncOptions(profile="compact")
    assert _run_once(OneRun(SyncReport("compact", "t0", retry_soon=True)), options) is False  # type: ignore[arg-type]
    assert _run_once(OneRun(SyncReport("compact", "t0", errors=["x: SHA-256 mismatch"])), options) is True  # type: ignore[arg-type]


def test_the_sync_loop_stops_cleanly_on_sigterm(zim_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[object] = []
    monkeypatch.setattr("app.cli_zim.stop_on_sigterm", lambda: installed.append("sigterm"))
    monkeypatch.setattr("app.cli_zim.run_periodically", lambda *args, **kwargs: None)
    assert main(["zim", "sync", "--offline", "--loop"]) == 0
    assert installed == ["sigterm"]


def test_the_sync_loop_signs_life_into_the_zim_directory(zim_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.cli_zim.run_periodically", lambda task, interval, **kwargs: captured.update(kwargs))
    assert main(["zim", "sync", "--offline", "--loop"]) == 0

    captured["alive"]()

    assert last_alive(zim_env / ALIVE_FILE) is not None  # what the API reports (kompendium_zim_sync_alive_...)


def test_status_before_the_first_sync_names_the_missing_archives(
    zim_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["zim", "status"]) == 0

    out = capsys.readouterr().out
    assert "active.json fehlt" in out
    assert "FEHLT    wikipedia_de_sample (Pflichtarchiv, /ready bleibt 503)" in out


def test_status_lists_retired_archives_and_the_running_download(
    zim_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["zim", "sync", "--offline"]) == 0
    state = read_active(zim_env)
    assert state is not None
    state.retired.append(RetiredArchive(file="klexikon_de_sample_2026-07.zim", retired_at="2026-09-01T00:00:00Z"))
    write_active(zim_env, state)
    download = {"file": "wikipedia_de_sample_2026-09.zim", "percent": 42, "speed_mb_s": 3.1}
    status = {"state": "downloading", "updated_at": "2026-10-08T09:00:00Z", "download": download}
    (zim_env / STATUS_FILE).write_text(json.dumps(status), encoding="utf-8")
    capsys.readouterr()

    assert main(["zim", "status"]) == 0

    out = capsys.readouterr().out
    assert "abgelöst klexikon_de_sample_2026-07.zim  seit 2026-09-01T00:00:00Z" in out
    assert "Letzter Sync: downloading (2026-10-08T09:00:00Z)" in out
    assert "Download wikipedia_de_sample_2026-09.zim: 42 % (3.1 MB/s)" in out


def catalog_answering(feed: Path, monkeypatch: pytest.MonkeyPatch) -> list[httpx.Client]:
    """The Kiwix catalog of the command answers every request with ``feed``; the clients it opened come back."""
    clients: list[httpx.Client] = []

    def catalog(url: str) -> KiwixCatalog:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=feed.read_bytes()))
        clients.append(httpx.Client(transport=transport))
        return KiwixCatalog(url, client=clients[-1])

    monkeypatch.setattr("app.cli_zim.KiwixCatalog", catalog)
    return clients


def test_catalog_lists_the_newest_dump_of_each_subscription_and_names_those_it_lacks(
    zim_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    maxi = (
        "  - {id: klexikon_de_all_maxi, name: klexikon_de_all, flavour: maxi, project: klexikon, profiles: [compact]}"
    )
    (zim_env.parent / "config" / "zim_subscriptions.yaml").write_text(MANIFEST_YAML + maxi + "\n", encoding="utf-8")
    clients = catalog_answering(OPDS / "klexikon_de_all.xml", monkeypatch)

    assert main(["zim", "catalog"]) == 0

    out = capsys.readouterr().out
    assert "nicht im Katalog: wikipedia_de_sample" in out and "nicht im Katalog: klexikon_de_sample" in out
    [listed] = [line for line in out.splitlines() if line.startswith("klexikon_de_all")]
    assert listed.startswith("klexikon_de_all_maxi ") and "klexikon_de_all_maxi_2026-08.zim" in listed
    assert all(client.is_closed for client in clients)


def test_catalog_all_lists_every_german_archive(
    zim_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog_answering(OPDS / "klexikon_de_all.xml", monkeypatch)

    assert main(["zim", "catalog", "--all"]) == 0

    listed = [line.split()[0] for line in capsys.readouterr().out.splitlines()]
    assert listed == ["klexikon_de_all_maxi", "klexikon_de_all_nopic"]


def test_ctrl_c_ends_the_sync_loop_without_a_traceback(
    zim_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("app.cli_zim.stop_on_sigterm", lambda: None)

    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("app.cli_zim.run_periodically", interrupted)

    assert main(["zim", "sync", "--offline", "--loop"]) == 0
    assert "Sync-Schleife beendet." in capsys.readouterr().out


def test_info_prints_the_metadata_of_each_archive(
    zim_env: Path, sample_zims: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["zim", "info", *(str(path) for path in sample_zims.values())]) == 0

    out, decoder, snapshots = capsys.readouterr().out, json.JSONDecoder(), []
    position = 0
    while out[position:].strip():
        snapshot, position = decoder.raw_decode(out, len(out) - len(out[position:].lstrip()))
        snapshots.append(snapshot)
    assert {snapshot["file"] for snapshot in snapshots} == {path.name for path in sample_zims.values()}
    assert {snapshot["project"] for snapshot in snapshots} == {"wikipedia", "klexikon"}
