"""What the archive logs when libzim refuses a lookup, a suggestion or a search (logging review of 2026-10-08).

Every exception was a DEBUG line and "not there": a damaged title or full-text index made every topic a 404 without
a word at INFO. Probed on the Klexikon archive, only a lone surrogate raises among odd inputs (UnicodeEncodeError);
that stays a detail. Any other error is a WARNING, once per kind of lookup and error class.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from app.sources.zim.archive import ZimArchive


class Broken:
    """Stands in for libzim's archive: every lookup raises ``error``."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def has_entry_by_title(self, title: str) -> Any:
        raise self.error

    has_entry_by_path = get_entry_by_title = get_entry_by_path = has_entry_by_title


def archive_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "app.sources.zim.archive"]


def test_a_lookup_libzim_refuses_is_a_warning_once(
    sample_zims: dict[str, Path], caplog: pytest.LogCaptureFixture
) -> None:
    archive = ZimArchive(sample_zims["klexikon"])
    archive._archive = Broken(RuntimeError("index damaged"))

    with caplog.at_level(logging.DEBUG, logger="app.sources.zim.archive"):
        assert not archive.has("Optik") and not archive.has("Licht")

    warnings = [record for record in archive_lines(caplog) if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "RuntimeError: index damaged" in warnings[0].getMessage() and archive.file_name in warnings[0].getMessage()


def test_odd_input_stays_a_detail(sample_zims: dict[str, Path], caplog: pytest.LogCaptureFixture) -> None:
    archive = ZimArchive(sample_zims["klexikon"])
    archive._archive = Broken(UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed"))

    with caplog.at_level(logging.DEBUG, logger="app.sources.zim.archive"):
        assert not archive.has("Opt\ud800ik")

    assert archive_lines(caplog) and all(record.levelno == logging.DEBUG for record in archive_lines(caplog))


def test_a_search_libzim_refuses_is_a_warning_once(
    sample_zims: dict[str, Path], caplog: pytest.LogCaptureFixture
) -> None:
    archive = ZimArchive(sample_zims["klexikon"])
    archive._archive = Broken(RuntimeError("index damaged"))

    with caplog.at_level(logging.DEBUG, logger="app.sources.zim.archive"):
        assert archive.suggest("Opt") == [] and archive.suggest("Lic") == []

    warnings = [record for record in archive_lines(caplog) if record.levelno == logging.WARNING]
    assert len(warnings) == 1 and "suggestion" in warnings[0].getMessage()
