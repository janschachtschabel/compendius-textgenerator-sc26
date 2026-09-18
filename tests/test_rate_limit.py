"""Requests per client and minute on the expensive endpoints (RATE_LIMIT, as in the old service)."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.limits import RateLimiter
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
