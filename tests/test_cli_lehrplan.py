"""CLI: ``compendium lehrplan status`` and ``lehrplan search`` against a temporary state directory."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.cli import main
from app.settings import get_settings
from tests.conftest import ROOT
from tests.test_lehrplan_api import write_cache


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
