"""CLI: ``compendium zim sync --offline`` and ``zim status`` against a temporary ZIM directory."""

import shutil
from collections.abc import Iterator
from pathlib import Path

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
