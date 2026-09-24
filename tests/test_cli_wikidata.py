"""``compendium wikidata build|status``: the index is built from dump files on disk, never from the network (D43)."""

from __future__ import annotations

import zlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.cli import main
from app.settings import get_settings
from tests.conftest import ROOT
from tests.test_wikidata_index import write_dumps


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
