"""CLI: ``compendium generate`` with the LLM switches on the offline sample archives (LLM off: everything falls back)."""

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
        "PRESET_DEFAULT": "llm-free",  # the shipped balanced needs an LLM (D53)
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_generate_refuses_llm_switches_without_an_llm(
    cli_env: Path, sample_zims: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """D53: what needs an LLM on a server without one is refused, as the API answers it with a 503."""
    out_file = cli_env / "optik.md"
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    switches = ["--extraction", "llm", "--generation", "llm-fast"]
    assert main(["generate", "--topic", "Optik", *switches, "--out", str(out_file), *zim_args]) == 1
    err = capsys.readouterr().err
    assert "LLM_ENABLED" in err and "extraction=llm" in err and "generation=llm-fast" in err
    assert not out_file.exists()


def test_generate_takes_the_curriculum_check_and_refuses_it_without_an_llm(
    cli_env: Path, sample_zims: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """D58: the switch of part 2 is on the command line too, and needs an LLM like the switches of part 1."""
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    assert main(["generate", "--topic", "Optik", "--curriculum-check", "llm", *zim_args]) == 1
    assert "curriculum_check=llm" in capsys.readouterr().err


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


def test_generate_takes_a_node_as_the_api_does(
    cli_env: Path, sample_zims: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI knew no node (review of 2026-09-25); --node-id and --repository work as node_id and repository."""
    client = EduSharingClient(BASE, transport=httpx.MockTransport(FakeRepository()))
    builder = CollectionBuilder(client=client, cache=None)
    monkeypatch.setattr("app.main.build_collections", lambda settings: builder)
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    out_file = cli_env / "knoten.md"
    assert main(["generate", "--node-id", OPTIK, "--out", str(out_file), *zim_args]) == 0
    assert "Thema: Optik" in capsys.readouterr().err and out_file.read_text(encoding="utf-8").strip()
    refused = ["generate", "--node-id", OPTIK, "--repository", "https://example.org/edu-sharing/rest", *zim_args]
    assert main(refused) == 1
    assert "example.org" in capsys.readouterr().err, "a refused address is named, not a traceback"


def test_generate_accepts_the_enrichment_switch_and_reports_sources_only_without_an_llm(
    cli_env: Path, sample_zims: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """docs/umbau.md U4: the switch is reachable from the CLI; without an LLM writing it cannot take effect."""
    out_file = cli_env / "optik.md"
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    switches = ["--enrichment", "model-knowledge"]
    assert main(["generate", "--topic", "Optik", *switches, "--out", str(out_file), *zim_args]) == 0
    assert "enrichment: sources-only" in out_file.read_text(encoding="utf-8")
    assert "Modellwissen" not in capsys.readouterr().err


def test_generate_rejects_an_unknown_enrichment(cli_env: Path) -> None:
    with pytest.raises(SystemExit):
        main(["generate", "--topic", "Optik", "--enrichment", "alles-erfinden"])


def test_generate_names_an_unknown_template_instead_of_a_traceback(
    cli_env: Path, sample_zims: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    assert main(["generate", "--topic", "Optik", "--template", "nope", *zim_args]) == 1
    assert "nope" in capsys.readouterr().err
