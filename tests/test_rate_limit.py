"""Requests per client and minute on the expensive endpoints (RATE_LIMIT, as in the old service)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.limits import RateLimiter, client_key
from app.main import create_app
from tests.conftest import make_settings


def test_limiter_counts_per_client_and_frees_slots_after_the_window() -> None:
    now = [0.0]
    limiter = RateLimiter(limit=1, window_s=60.0, clock=lambda: now[0])
    assert limiter.retry_after("a") is None
    assert limiter.retry_after("a") == 60
    assert limiter.retry_after("b") is None  # every client has its own window
    now[0] = 60.5
    assert limiter.retry_after("a") is None


def test_the_limit_answers_429_with_retry_after_and_spares_the_probes(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    settings = make_settings(sample_zims.values(), tmp_path / "state", rate_limit=2)
    with TestClient(create_app(settings)) as client:
        codes = [client.get("/api/v2/lehrplan/search", params={"q": "Optik"}).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        limited = client.post("/api/v2/compendium", json={"topic": "Optik"})
        assert limited.status_code == 429 and int(limited.headers["Retry-After"]) >= 1
        assert [client.get(path).status_code for path in ("/health", "/ready", "/api/v2/templates")] == [200] * 3


def test_zero_switches_the_limit_off(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    settings = make_settings(sample_zims.values(), tmp_path / "state", rate_limit=0)
    with TestClient(create_app(settings)) as client:
        codes = {client.get("/api/v2/lehrplan/search", params={"q": "Optik"}).status_code for _ in range(5)}
        assert codes == {200}


def test_the_addresses_of_one_ipv6_64_share_a_window() -> None:
    """A connection often holds a whole /64: address by address, one client had a window per address (SE-07)."""
    limiter = RateLimiter(limit=2)

    assert limiter.retry_after(client_key("2001:db8:1:2::1")) is None
    assert limiter.retry_after(client_key("2001:db8:1:2:ffff::7")) is None
    assert limiter.retry_after(client_key("2001:db8:1:2::abcd")) is not None
    assert limiter.retry_after(client_key("2001:db8:1:3::1")) is None  # the next /64 counts apart


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("192.0.2.7", "192.0.2.7"),
        ("::ffff:192.0.2.7", "192.0.2.7"),
        ("unbekannt", "unbekannt"),
        ("testclient", "testclient"),
    ],
)
def test_an_ipv4_client_counts_by_its_address(host: str, key: str) -> None:
    assert client_key(host) == key


def test_the_windows_are_bounded_and_the_least_recent_client_goes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Idle windows were dropped by a scan over all of them on every request, and only idle ones: 30,000 active
    clients cost 6.8 ms per request, with no bound on their number (audit 2026-09-27, SE-07)."""
    monkeypatch.setattr("app.api.limits.MAX_CLIENTS", 3)
    limiter = RateLimiter(limit=1)
    for client in ("a", "b", "c"):
        assert limiter.retry_after(client) is None
    assert limiter.retry_after("a") is not None  # limited, and now the most recently seen

    assert limiter.retry_after("d") is None  # b, the least recently seen, makes room
    assert len(limiter) == 3
    assert limiter.retry_after("b") is None  # b starts afresh
    assert limiter.retry_after("a") is not None  # a kept its window
