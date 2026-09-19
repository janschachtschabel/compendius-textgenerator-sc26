"""Matching endpoints: strategies and the comparator with and without a gold file."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.requests import GenerateRequest
from app.main import create_app
from app.matching.gold import GoldLabel, GoldSet, save_gold, text_hash
from app.settings import Settings
from tests.conftest import make_settings

AUTH = {"X-Admin-Token": "s3cret"}


@pytest.fixture(scope="module")
def gold_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("gold")


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], gold_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings: Settings = make_settings(
        sample_zims.values(), tmp_path_factory.mktemp("state"), eval_gold_dir=gold_dir, admin_token="s3cret"
    )
    return TestClient(create_app(settings), headers=AUTH)


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


def test_compare_is_an_admin_tool(client: TestClient) -> None:
    payload = {"topic": "Optik", "matchers": ["bm25"]}
    assert client.post("/api/v2/matching/compare", json=payload, headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert client.get("/api/v2/matching/strategies", headers={"X-Admin-Token": "wrong"}).status_code == 200


def test_compare_runs_every_strategy_once(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    service = client.app.state.service  # type: ignore[attr-defined]
    original, runs = service.match, []

    def counting(*args: Any, **kwargs: Any) -> Any:
        runs.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "match", counting)
    response = client.post("/api/v2/matching/compare", json={"topic": "Optik", "matchers": ["bm25"] * 8})
    assert response.status_code == 200 and runs == ["bm25"]


def test_compare_with_an_unknown_template_is_404(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    settings = make_settings(sample_zims.values(), tmp_path, admin_token="s3cret")
    with TestClient(create_app(settings), headers=AUTH, raise_server_exceptions=False) as client:
        response = client.post("/api/v2/matching/compare", json={"topic": "Optik", "template_id": "gibtsnicht"})
    assert response.status_code == 404 and response.json()["detail"] == "Template nicht gefunden: gibtsnicht"
