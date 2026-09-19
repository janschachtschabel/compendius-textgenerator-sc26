"""Legacy pipeline and translate (PLAN.md 8.1): the three steps in one answer, translation only with an LLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("v1pipe") / "state")
    return TestClient(create_app(settings))


def test_the_pipeline_answers_its_four_blocks(client: TestClient) -> None:
    payload = {"text": "Optik", "config": {"compendium": {"length": 6000}, "qa": {"num_pairs": 3}}}
    response = client.post("/api/v1/pipeline", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "original_text",
        "linker_output",
        "compendium_output",
        "qa_output",
        "pipeline_statistics",
    }
    assert body["linker_output"]["entities"] and body["compendium_output"]["markdown"].startswith("---")
    qa = body["qa_output"]
    assert qa["original_text"] == body["compendium_output"]["markdown"]  # the pairs are about the compendium
    assert 0 < len(qa["qa"]) <= 3
    assert set(qa["qa"][0]) == {"question", "answer", "level_property", "level_value"}
    statistics = body["pipeline_statistics"]
    assert set(statistics["processing_times"]) == {"linker", "compendium", "qa"}
    assert statistics["completed_steps"] == 3 and statistics["total_steps"] == 3 and statistics["errors"] == []


def test_the_pipeline_reads_the_qa_settings_from_its_config(client: TestClient) -> None:
    payload = {"text": "Optik", "num_pairs": 99, "config": {"qa": {"num_pairs": 2}}}
    body = client.post("/api/v1/pipeline", json=payload).json()
    assert len(body["qa_output"]["qa"]) <= 2, "config.qa decides, the top-level field is only tolerated"
    assert client.post("/api/v1/pipeline", json={"text": ""}).status_code == 422
    assert client.post("/api/v1/pipeline", json={"text": "  "}).status_code == 400
    assert client.post("/api/v1/pipeline", json={"text": "Xyzzyplomb"}).status_code == 404
    too_short = {"text": "Optik", "config": {"compendium": {"length": 500}}}
    assert client.post("/api/v1/pipeline", json=too_short).status_code == 422  # the old bounds still apply here


def test_translate_needs_an_llm_and_says_so(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    response = client.post("/api/v1/utils/translate", json={"text": "Hallo", "target_lang": "en"})
    assert response.status_code == 503 and "LLM" in response.text

    def answer(body: dict[str, Any]) -> str:
        assert "en" in body["messages"][1]["content"] and "Hallo" in body["messages"][1]["content"]
        return "Hello"

    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(FakeBApi(answer)))  # type: ignore[attr-defined]
    body = client.post("/api/v1/utils/translate", json={"text": "Hallo", "target_lang": "en"}).json()
    assert body == {"translation": "Hello"}
    assert client.post("/api/v1/utils/translate", json={"text": ""}).status_code == 422


def test_a_failing_translation_is_a_status_code_not_a_fake_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(FakeBApi(statuses=[400] * 3)))  # type: ignore[attr-defined]
    response = client.post("/api/v1/utils/translate", json={"text": "Hallo", "target_lang": "en"})
    assert response.status_code == 502 and "b-api" in response.text
