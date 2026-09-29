"""A damaged local index answers nothing, and the sync builds it anew (audit 2026-09-27, DB-01).

The builds write without journal and without synchronous, and the swap used to follow without fsync: after a crash
or a full disk a page can be broken. A lookup that met one raised "database disk image is malformed" into every
request (500), while ``available`` stayed true - it only reads the meta rows - and the sync kept the index.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.sources.gnd.index import GndIndex, build_gnd_index
from tests.test_gnd_index import write_dumps
from tests.test_gnd_sync import FakeDnb, _sync


@pytest.fixture
def dnb(tmp_path: Path) -> FakeDnb:
    return FakeDnb(tmp_path / "dnb")


def built(directory: Path) -> Path:
    path = directory / "gnd.db"
    build_gnd_index(write_dumps(directory / "dumps"), path)
    return path


def damage(path: Path, table: str) -> None:
    """Overwrite the root page of ``table`` with garbage, as a torn write would leave it."""
    with sqlite3.connect(path) as connection:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        root = connection.execute("SELECT rootpage FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
    connection.close()
    with path.open("r+b") as handle:
        handle.seek((root - 1) * page_size)
        handle.write(bytes([255]) * page_size)


def test_a_lookup_that_meets_a_damaged_page_answers_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = built(tmp_path)
    damage(path, "names")
    index = GndIndex(path)
    assert index.available  # the meta rows are whole, so the file looks usable

    with caplog.at_level("ERROR"):
        hit = index.find("Optik", None)

    assert hit is None
    assert not index.available  # /health and the gauge see it from now on
    assert "not usable" in caplog.text
    assert index.find("Optik", None) is None  # and the next lookup asks nothing


def test_the_check_of_the_sync_finds_a_damaged_page(tmp_path: Path, dnb: FakeDnb) -> None:
    state = tmp_path / "state"
    state.mkdir()
    damage(built(state), "names")

    assert _sync(state, dnb).due() == "index unusable"


def test_an_intact_index_passes_the_check(tmp_path: Path) -> None:
    with closing(GndIndex(built(tmp_path))) as index:
        assert index.intact()


def test_the_new_index_reaches_the_disk_before_it_replaces_the_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(descriptor: int) -> None:
        events.append("fsync")
        real_fsync(descriptor)

    def replace(source: str | Path, target: str | Path) -> None:
        events.append("replace")
        real_replace(source, target)

    monkeypatch.setattr("app.sources.local_index.os.fsync", fsync)
    monkeypatch.setattr("app.sources.local_index.os.replace", replace)

    built(tmp_path)

    assert "fsync" in events and events.index("fsync") < events.index("replace")
