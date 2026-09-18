"""Matching endpoints: strategies and the comparator with and without a gold file."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.requests import GenerateRequest
from app.main import create_app
from app.matching.gold import GoldLabel, GoldSet, save_gold, text_hash
from app.settings import Settings
from tests.conftest import make_settings


@pytest.fixture(scope="module")
def gold_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("gold")


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], gold_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings: Settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("state"), eval_gold_dir=gold_dir)
    return TestClient(create_app(settings))


def test_strategies_are_listed(client: TestClient) -> None:
    strategies = client.get("/api/v2/matching/strategies").json()
    assert any(s["id"] == "hybrid_light" and s["recommended"] for s in strategies)


def test_compare_without_gold_reports_agreement(client: TestClient) -> None:
    response = client.post("/api/v2/matching/compare", json={"topic": "Optik", "matchers": ["bm25", "hybrid_light"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["topic"] == "Optik"
    assert body["chunks"] > 10
    assert body["gold"] is None
    assert set(body["results"]) == {"bm25", "hybrid_light"}
    assert body["results"]["hybrid_light"]["assigned"] > 0
    assert body["results"]["hybrid_light"]["metrics"] is None
    assert 0.0 <= body["agreement"]["bm25|hybrid_light"] <= 1.0


def test_compare_with_gold_returns_metrics(client: TestClient, gold_dir: Path) -> None:
    prepared = client.app.state.service.prepare(GenerateRequest(topic="Optik"))
    lead = next(c for c in prepared.chunks if c.is_lead)
    gold = GoldSet(
        topic="Optik",
        labeled_by="test",
        labels=[GoldLabel(chunk_id=lead.chunk_id, slot="themendefinition", text_hash=text_hash(lead.text))],
    )
    save_gold(gold_dir / "optik.jsonl", gold)
    response = client.post("/api/v2/matching/compare", json={"topic": "optik", "matchers": ["hybrid_light"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gold"] == {"topic": "Optik", "labeled": 1, "stale": 0, "labeled_by": "test"}
    metrics = body["results"]["hybrid_light"]["metrics"]
    assert metrics["macro_f1"] == pytest.approx(1.0)
    assert metrics["labeled"] == 1


def test_compare_rejects_unknown_matcher_and_topic(client: TestClient) -> None:
    assert client.post("/api/v2/matching/compare", json={"topic": "Optik", "matchers": ["magic"]}).status_code == 422
    response = client.post("/api/v2/matching/compare", json={"topic": "Xyzzyplomb"})
    assert response.status_code == 404
    assert response.json()["detail"]["resolution"]["normalized"] == "Xyzzyplomb"
