"""Legacy QA (PLAN.md 8.1, D14): pairs from the LLM when it is configured, from question templates otherwise."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.synthesis.qa import rule_based_pairs
from tests.conftest import make_settings
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

TEXT = (
    "Die Optik ist ein Teilgebiet der Physik, das sich mit dem Licht befasst. "
    "Die Wellenoptik beschreibt das Licht als Welle. "
    "Ein Fernrohr besteht aus mehreren Linsen. "
    "Im Jahr 1608 wurde das erste Fernrohr gebaut. "
    "Brillen dienen der Korrektur von Fehlsichtigkeit."
)


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("v1qa") / "state")
    return TestClient(create_app(settings))


def test_rules_ask_about_definitions_years_parts_and_purpose() -> None:
    pairs = rule_based_pairs(TEXT, limit=10, max_answer_length=400)
    questions = [pair.question for pair in pairs]
    assert "Was versteht man unter Optik?" in questions
    assert any(question.startswith("Was geschah im Jahr 1608") for question in questions)
    assert any("Woraus besteht" in question for question in questions)
    assert any("Wozu dienen Brillen" in question or "Wozu dient" in question for question in questions)
    assert all(pair.answer.endswith((".", "…")) and pair.level_value is None for pair in pairs)
    assert rule_based_pairs("", limit=5, max_answer_length=400) == []


def test_the_answer_is_cut_to_the_requested_length() -> None:
    pairs = rule_based_pairs(TEXT, limit=3, max_answer_length=50)
    assert pairs and all(len(pair.answer) <= 50 for pair in pairs)
    assert any(pair.answer.endswith("…") for pair in pairs)


def test_without_an_llm_the_endpoint_answers_from_the_templates(client: TestClient) -> None:
    response = client.post("/api/v1/qa", json={"text": TEXT, "num_pairs": 4})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"original_text", "qa"}
    assert body["original_text"] == TEXT and 0 < len(body["qa"]) <= 4
    first = body["qa"][0]
    assert set(first) == {"question", "answer", "level_property", "level_value"}
    assert first["level_property"] is None and first["level_value"] is None


def test_levels_are_echoed_without_an_llm_and_filled_with_one(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {"text": TEXT, "num_pairs": 2, "level_property": "Bildungsstufe", "level_values": ["Sek I", "Sek II"]}
    body = client.post("/api/v1/qa", json=payload).json()
    assert [pair["level_property"] for pair in body["qa"]] == ["Bildungsstufe"] * len(body["qa"])
    assert all(pair["level_value"] is None for pair in body["qa"]), "the distribution needs the LLM"

    def answer(body: dict[str, Any]) -> str:
        assert "Bildungsstufe" in body["messages"][1]["content"]
        return "1. Was ist Licht?;Licht ist eine Welle.;Sek I\nWas ist Optik?;Ein Teilgebiet der Physik.;Sek III"

    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(FakeBApi(answer)))  # type: ignore[attr-defined]
    with_llm = client.post("/api/v1/qa", json=payload).json()["qa"]
    assert [pair["question"] for pair in with_llm] == ["Was ist Licht?", "Was ist Optik?"]  # numbering stripped
    assert [pair["level_value"] for pair in with_llm] == ["Sek I", "Sek I"]  # unknown level falls to the first
    assert all(pair["level_property"] == "Bildungsstufe" for pair in with_llm)


def test_a_failing_llm_falls_back_to_the_templates(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = make_gateway(FakeBApi(statuses=[400] * 5))
    monkeypatch.setattr(client.app.state.service, "llm", gateway)  # type: ignore[attr-defined]
    body = client.post("/api/v1/qa", json={"text": TEXT, "num_pairs": 3}).json()
    assert body["qa"] and all(pair["answer"] for pair in body["qa"])


def test_the_qa_endpoint_validates_like_the_old_one(client: TestClient) -> None:
    assert client.post("/api/v1/qa", json={"text": ""}).status_code == 422
    assert client.post("/api/v1/qa", json={"text": "   "}).status_code == 400
    assert client.post("/api/v1/qa", json={"text": TEXT, "num_pairs": 0}).status_code == 422
    assert client.post("/api/v1/qa", json={"text": TEXT, "max_answer_length": 10}).status_code == 422
