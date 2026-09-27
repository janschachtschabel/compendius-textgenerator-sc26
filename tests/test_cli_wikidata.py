"""``compendium wikidata build|status``: the index is built from dump files on disk, never from the network (D43)."""

from __future__ import annotations

import zlib
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from app.cli import main
from app.settings import Settings, get_settings
from app.sources.wikidata.index import WikidataIndex
from app.sources.wikidata.sync import WikidataSync
from tests.conftest import ROOT
from tests.test_wikidata_index import write_dumps
from tests.test_wikidata_sync import FakeDumps


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


def test_status_before_and_after_a_build(state_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["wikidata", "status"]) == 0
    assert "kein Wikidata-Index" in capsys.readouterr().out

    page_props, page = write_dumps(tmp_path / "dumps")
    assert main(["wikidata", "build", "--page-props", str(page_props), "--page", str(page)]) == 0
    assert "5 Artikel" in capsys.readouterr().out
    assert (state_dir / "wikidata.db").is_file()

    assert main(["wikidata", "status"]) == 0
    out = capsys.readouterr().out
    assert "5 Artikel" in out and "2026-09-07" in out


def test_a_missing_dump_file_fails_with_a_message(
    state_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["wikidata", "build", "--page-props", str(tmp_path / "fehlt.gz"), "--page", str(tmp_path / "auch.gz")])
    assert code == 1
    assert "fehlt.gz" in capsys.readouterr().err
    assert not (state_dir / "wikidata.db").exists()


def test_a_truncated_dump_fails_with_a_message(
    state_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An interrupted download ends the gzip stream early; that is a message, not a traceback."""
    page_props, page = write_dumps(tmp_path / "dumps")
    cut = tmp_path / "cut-page.sql.gz"
    cut.write_bytes(page.read_bytes()[:-40])
    assert main(["wikidata", "build", "--page-props", str(page_props), "--page", str(cut)]) == 1
    assert "nicht gebaut" in capsys.readouterr().err
    assert not (state_dir / "wikidata.db").exists()


def test_a_damaged_dump_fails_with_a_message(
    state_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def damaged(*args: object) -> None:
        raise zlib.error("Error -3 while decompressing data: invalid distance too far back")

    monkeypatch.setattr("app.cli_wikidata.build_index", damaged)
    page_props, page = write_dumps(tmp_path / "dumps")
    assert main(["wikidata", "build", "--page-props", str(page_props), "--page", str(page)]) == 1
    assert "invalid distance" in capsys.readouterr().err


def test_an_index_in_use_is_kept_and_the_new_one_waits_beside_it(
    state_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(source: object, destination: object) -> None:
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr("app.sources.wikidata.index.os.replace", refuse)
    page_props, page = write_dumps(tmp_path / "dumps")
    assert main(["wikidata", "build", "--page-props", str(page_props), "--page", str(page)]) == 1
    err = capsys.readouterr().err
    assert "nicht übernommen" in err and "wikidata.db.part" in err
    assert (state_dir / "wikidata.db.part").is_file()


def _fake_sync(monkeypatch: pytest.MonkeyPatch, site: FakeDumps) -> None:
    def build(settings: Settings) -> WikidataSync:
        client = httpx.Client(transport=httpx.MockTransport(site.handler))
        return WikidataSync(settings.wikidata_db_path, client=client, base_url="https://dumps.wikimedia.org")

    monkeypatch.setattr("app.cli_wikidata.build_sync", build)


def test_sync_builds_a_missing_index_from_the_newest_run(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeDumps(tmp_path / "site")
    site.add("20260901", "2026-09-07 16:21:03")
    _fake_sync(monkeypatch, site)
    assert main(["wikidata", "sync"]) == 0
    out = capsys.readouterr().out
    assert "kein Index vorhanden" in out and "Dump vom 2026-09-07" in out
    assert WikidataIndex(state_dir / "wikidata.db").qid("Ernst Abbe") == "Q999001"


def test_sync_leaves_a_current_index_and_force_rebuilds_it(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeDumps(tmp_path / "site")
    site.add("20260901", "2026-09-07 16:21:03")
    _fake_sync(monkeypatch, site)
    assert main(["wikidata", "sync"]) == 0
    site.calls.clear()
    assert main(["wikidata", "sync"]) == 0
    assert "aktuell" in capsys.readouterr().out and site.downloads() == []
    assert main(["wikidata", "sync", "--force"]) == 0
    assert "erzwungen" in capsys.readouterr().out and len(site.downloads()) == 2


def test_a_failed_sync_keeps_the_old_index_and_says_why(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    site = FakeDumps(tmp_path / "site")
    site.add("20260901", "2026-09-04 18:02:11", page_done=False)
    _fake_sync(monkeypatch, site)
    assert main(["wikidata", "sync"]) == 1
    assert "nicht gebaut" in capsys.readouterr().err
    assert not (state_dir / "wikidata.db").exists()


def test_the_sync_loop_checks_at_the_interval_of_the_settings(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = FakeDumps(tmp_path / "site")
    site.add("20260901", "2026-09-07 16:21:03")
    _fake_sync(monkeypatch, site)
    seen: dict[str, object] = {}

    def once(task: Callable[[], object], interval: timedelta, **options: object) -> None:
        seen.update(interval=interval, **options)
        task()

    monkeypatch.setattr("app.cli_wikidata.run_periodically", once)
    monkeypatch.setattr("app.cli_wikidata.stop_on_sigterm", lambda: None)
    assert main(["wikidata", "sync", "--loop"]) == 0
    assert seen["interval"] == timedelta(days=1) and seen["retry_after"] == timedelta(hours=1)
    assert (state_dir / "wikidata.db").exists()
