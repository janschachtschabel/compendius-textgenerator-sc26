"""Matching endpoint: the strategies. The comparator left the API (D50); ``compendium eval`` compares on gold."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

AUTH = {"X-Admin-Token": "s3cret"}


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("state"), admin_token="s3cret")
    return TestClient(create_app(settings), headers=AUTH)


def test_strategies_are_listed(client: TestClient) -> None:
    strategies = client.get("/api/v2/matching/strategies").json()
    assert any(s["id"] == "hybrid_light" and s["recommended"] for s in strategies)


def test_the_comparator_left_the_api(client: TestClient) -> None:
    """Jan, 2026-09-25: no longer needed in production; compendium eval runs the same comparison (D50)."""
    assert client.post("/api/v2/matching/compare", json={"topic": "Optik"}).status_code == 404
    spec = client.get("/openapi.json").json()
    assert "/api/v2/matching/compare" not in spec["paths"]
    assert "CompareRequest" not in spec["components"]["schemas"]
