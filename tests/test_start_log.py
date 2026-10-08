"""The start of the API in the log: version, revision and what it runs with (logging review of 2026-10-08).

After a panel update the revision could be read from /health only, and the log of an error said nothing of the code
that wrote it; a first start did not say that part 2 had no cache yet or /entities no index.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app import __version__
from app.main import create_app
from tests.conftest import make_settings


def start_line(caplog: pytest.LogCaptureFixture) -> str:
    [line] = [record.getMessage() for record in caplog.records if record.getMessage().startswith("Kompendium-API ")]
    return line


def test_the_start_names_version_revision_and_what_runs(
    sample_zims: dict[str, Path], tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_REVISION", "abc1234")
    settings = make_settings(sample_zims.values(), tmp_path / "state", api_keys="k" * 16 + "," + "q" * 16)

    with caplog.at_level(logging.INFO, logger="app.main"):
        create_app(settings).state.service.close()

    line = start_line(caplog)
    assert line.startswith(f"Kompendium-API {__version__} (revision abc1234) started: ")
    for part in (
        "archives 2 (required 2 of 2)",
        "LLM off",
        "lehrplan cache missing",
        "wikidata index missing",
        "gnd index missing",
        f"edu-sharing {urlparse(settings.edu_sharing_base_url).hostname}",  # the repository it reads, no path
        "API_KEYS 2",
        "METRICS_TOKEN not set",
        "admin off",
    ):
        assert part in line, part


def test_a_missing_required_archive_is_named_at_the_start(
    sample_zims: dict[str, Path], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """/ready answered 503 for a missing required archive, while the log said only which archives had loaded."""
    required = "wikipedia_de_sample,klexikon_de_sample,wikibooks_de_sample"
    settings = make_settings(sample_zims.values(), tmp_path / "state", zim_required=required)

    with caplog.at_level(logging.INFO, logger="app.main"):
        create_app(settings).state.service.close()

    [warning] = [record for record in caplog.records if record.levelno == logging.WARNING and "required" in record.msg]
    assert "wikibooks_de_sample" in warning.getMessage() and "/ready" in warning.getMessage()
    assert "archives 2 (required 2 of 3)" in start_line(caplog)
