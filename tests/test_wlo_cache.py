"""TTL cache for repository answers: SQLite file, expiry by injected clock, JSON values."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.main import create_app
from app.sources.wlo.cache import TtlCache
from tests.conftest import make_settings


def test_roundtrip_expiry_and_overwrite(tmp_path: Path) -> None:
    now = [1_000.0]
    cache = TtlCache(tmp_path / "wlo_cache.db", clock=lambda: now[0])
    assert cache.get("collection:1") is None
    cache.set("collection:1", {"title": "Optik", "n": 16}, ttl_s=60)
    assert cache.get("collection:1") == {"title": "Optik", "n": 16}
    now[0] += 59
    assert cache.get("collection:1") is not None
    now[0] += 2
    assert cache.get("collection:1") is None  # expired
    cache.set("collection:1", ["fresh"], ttl_s=10)
    assert cache.get("collection:1") == ["fresh"]
    assert (tmp_path / "wlo_cache.db").exists()


def test_two_instances_share_the_file(tmp_path: Path) -> None:
    path = tmp_path / "wlo_cache.db"
    TtlCache(path, clock=lambda: 0.0).set("k", "v", ttl_s=100)
    assert TtlCache(path, clock=lambda: 50.0).get("k") == "v"


def test_writes_sweep_expired_entries_of_other_keys(tmp_path: Path) -> None:
    now = [0.0]
    path = tmp_path / "wlo_cache.db"
    cache = TtlCache(path, clock=lambda: now[0])
    cache.set("text:old", "a" * 1000, ttl_s=10)
    now[0] += 20
    cache.set("text:new", "b", ttl_s=10)  # nobody will ask for text:old again; the write removes it
    with closing(sqlite3.connect(path)) as connection:
        assert [row[0] for row in connection.execute("SELECT key FROM cache")] == ["text:new"]


def test_an_unusable_cache_file_degrades_to_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cache = TtlCache(tmp_path / "wlo_cache.db")

    def locked(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache, "_connect", locked)
    with caplog.at_level("WARNING"):
        assert cache.get("collection:1") is None
        cache.set("collection:1", {"title": "Optik"}, ttl_s=60)  # the cache only saves time; no exception
    assert "database is locked" in caplog.text


def test_a_corrupt_cache_file_does_not_stop_the_start(
    sample_zims: dict[str, Path], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "wlo_cache.db").write_bytes(b"not a database at all")
    with caplog.at_level("WARNING"):
        app = create_app(make_settings(sample_zims.values(), state))  # a DatabaseError before
    assert app.state.collections is not None and app.state.collections.cache is None  # reads go to the repository
    assert "wlo_cache.db" in caplog.text


def test_the_sweep_of_expired_entries_uses_an_index(tmp_path: Path) -> None:
    path = tmp_path / "wlo_cache.db"
    TtlCache(path)
    with closing(sqlite3.connect(path)) as connection:
        plan = connection.execute("EXPLAIN QUERY PLAN DELETE FROM cache WHERE expires_at <= ?", (0,)).fetchall()
    # Every write sweeps; a full scan would cost time in proportion to the whole cache
    assert "USING INDEX" in " ".join(str(row[-1]) for row in plan), plan
