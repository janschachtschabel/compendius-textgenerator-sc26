"""The service says which matcher it really runs with (PLAN.md 4.4, D20).

Model2Vec is optional: a missing or unreadable model leaves the matcher with BM25 and char TF-IDF, and the
answers get measurably weaker (eval/README.md). Without this the degradation is silent - a warning in the log
that nobody reads. So the components belong in /health, where an operator and a monitor can see them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.matching.registry import active_components
from tests.conftest import make_settings


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("m") / "state")
    return TestClient(create_app(settings))


def test_health_names_the_matcher_and_its_components(client: TestClient) -> None:
    matching = client.get("/health").json()["components"]["matching"]
    assert matching["matcher"] == "hybrid_light"
    assert matching["components"] == ["bm25", "char_tfidf"]  # no model configured in the tests
    assert matching["embeddings"] is False


def test_a_missing_model_does_not_count_as_an_embedding_component(tmp_path: Path) -> None:
    assert active_components("hybrid_light", str(tmp_path / "nothing-here")) == ["bm25", "char_tfidf"]


def test_a_matcher_without_components_names_itself() -> None:
    assert active_components("bm25", "") == ["bm25"]
