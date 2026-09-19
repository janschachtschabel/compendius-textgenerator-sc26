"""CLI: ``compendium generate --mode`` on the offline sample archives (LLM off, so hybrid requests fall back)."""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.cli import main
from app.settings import get_settings
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.conftest import ROOT
from tests.test_wlo_client import BASE, OPTIK, FakeRepository


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    env = {
        "STATE_DIR": str(tmp_path / "state"),
        "CONFIG_DIR": str(ROOT / "config"),
        "ZIM_PATHS": "",
        "LLM_ENABLED": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_generate_accepts_a_generation_switch_and_reports_the_fallback(
    cli_env: Path, sample_zims: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    out_file = cli_env / "optik.md"
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    assert main(["generate", "--topic", "Optik", "--generation", "llm-fast", "--out", str(out_file), *zim_args]) == 0
    err = capsys.readouterr().err
    assert "Generierung: rule-based" in err and "angefordert llm-fast" in err and "nicht konfiguriert" in err
    text = out_file.read_text(encoding="utf-8")
    assert "generation: rule-based" in text and "generation_requested: llm-fast" in text


def test_generate_rejects_an_unknown_generation(cli_env: Path) -> None:
    with pytest.raises(SystemExit) as info:
        main(["generate", "--topic", "Optik", "--generation", "turbo"])
    assert info.value.code == 2


def test_generate_reports_a_repository_failure_once(
    cli_env: Path, sample_zims: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = EduSharingClient(BASE, transport=httpx.MockTransport(FakeRepository(fail=True)))
    builder = CollectionBuilder(client=client, cache=None)
    monkeypatch.setattr("app.main.build_collections", lambda settings: builder)  # imported when the command runs
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    assert main(["generate", "--collection-id", OPTIK, *zim_args]) == 1
    err = capsys.readouterr().err
    assert "edu-sharing nicht erreichbar" in err and err.count("edu-sharing") == 1, err
