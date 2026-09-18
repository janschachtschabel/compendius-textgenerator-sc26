"""TTL cache for repository answers: SQLite file, expiry by injected clock, JSON values."""

from pathlib import Path

from app.sources.wlo.cache import TtlCache


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
