"""CLI: ``compendium templates`` (docs/umbau.md U6).

Listing worked before; writing and deleting had no way in at all. The bare command keeps listing, so an
existing habit is not broken by the two new verbs.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.cli import main
from app.settings import get_settings
from tests.conftest import ROOT

TEMPLATE = {"id": "mein", "name": "Mein Template", "slots": [{"id": "a", "slot": "praxis", "title": "Praxis"}]}


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CONFIG_DIR", str(ROOT / "config"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def write_template(directory: Path, data: dict[str, object]) -> Path:
    path = directory / "vorlage.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_bare_command_still_lists(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["templates"]) == 0
    assert "sc26" in capsys.readouterr().out


def test_save_and_delete_round_trip(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_template(cli_env, TEMPLATE)
    assert main(["templates", "save", str(path)]) == 0
    assert "mein" in capsys.readouterr().out
    assert main(["templates"]) == 0
    assert "mein" in capsys.readouterr().out

    assert main(["templates", "delete", "mein"]) == 0
    capsys.readouterr()  # drain the confirmation, so the next read holds the listing alone
    assert main(["templates"]) == 0
    assert "mein" not in capsys.readouterr().out


def test_saving_a_builtin_id_is_refused(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_template(cli_env, {**TEMPLATE, "id": "sc26"})
    assert main(["templates", "save", str(path)]) == 1
    assert "sc26" in capsys.readouterr().err


def test_an_unreadable_file_is_reported_not_raised(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["templates", "save", str(cli_env / "gibtesnicht.json")]) == 1
    assert "gibtesnicht.json" in capsys.readouterr().err
    broken = cli_env / "kaputt.json"
    broken.write_text("{kein json", encoding="utf-8")
    assert main(["templates", "save", str(broken)]) == 1


def test_deleting_something_that_is_not_there_is_reported(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["templates", "delete", "gibtesnicht"]) == 1
    assert "gibtesnicht" in capsys.readouterr().err
