"""CLI: ``compendium collection overview <id>`` against a fake repository."""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.cli import main
from app.settings import get_settings
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.conftest import ROOT
from tests.test_wlo_client import BASE, OPTIK, FakeRepository


@pytest.fixture
def fake_repository(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeRepository]:
    env = {"STATE_DIR": str(tmp_path / "state"), "CONFIG_DIR": str(ROOT / "config"), "ZIM_PATHS": ""}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    repo = FakeRepository()
    builder = CollectionBuilder(
        client=EduSharingClient(BASE, transport=httpx.MockTransport(repo), page_size=10),
        cache=TtlCache(tmp_path / "state" / "wlo_cache.db"),
    )
    monkeypatch.setattr("app.cli_collection.build_collections", lambda settings: builder)
    yield repo
    get_settings.cache_clear()


def test_overview_command_prints_part_three(
    fake_repository: FakeRepository, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out_file = tmp_path / "optik_teil3.md"
    assert main(["collection", "overview", OPTIK, "--out", str(out_file)]) == 0
    text = out_file.read_text(encoding="utf-8")
    assert text.startswith("## Teil 3 · Die Sammlung im Überblick") and "16 Inhalte" in text
    assert "16 Inhalte" in capsys.readouterr().out
    assert main(["collection", "overview", "not-a-uuid"]) == 1
