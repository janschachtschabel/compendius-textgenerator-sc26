"""Contract of the legacy endpoints (PLAN.md 8.1): the request shape of the old service, honest status codes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

LINKER_DATA = {  # as the old /api/v1/linker answered, and as tests/test_compendium.py of the old service sent it
    "original_text": "Optik",
    "entities": [
        {
            "entity": "Optik",
            "details": {"typ": "TOPIC", "citation": "Optik"},
            "sources": {
                "wikipedia": {
                    "status": "found",
                    "label_de": "Optik",
                    "label_en": "Optics",
                    "url_de": "https://de.wikipedia.org/wiki/Optik",
                    "url_en": "https://en.wikipedia.org/wiki/Optics",
                    "extract": "Die Optik ist ein Teilgebiet der Physik.",
                }
            },
        }
    ],
}


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("v1") / "state")
    return TestClient(create_app(settings))


def _statistics(body: dict[str, Any]) -> dict[str, Any]:
    stats: dict[str, Any] = body["statistics"]
    return stats


def test_compendium_from_text_answers_the_old_keys(client: TestClient) -> None:
    payload = {"input_type": "text", "text": "Optik", "config": {"length": 6000}}
    response = client.post("/api/v1/compendium", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"markdown", "bibliography", "statistics"}
    assert body["markdown"].startswith("---")  # frontmatter, then the compendium
    assert "Optik" in body["markdown"] and body["bibliography"].startswith("## ")
    stats = _statistics(body)
    for key in ("topic", "input_type", "input_length", "output_length", "references_count"):
        assert key in stats, key
    assert stats["input_type"] == "text" and stats["topic"] == "Optik"
    assert stats["output_length"] == len(body["markdown"]) and stats["references_count"] > 0
    assert stats["audit"]["matcher"] and stats["notes"] == []


def test_compendium_from_a_linker_output_uses_its_text_and_entities(client: TestClient) -> None:
    payload = {"input_type": "linker_output", "linker_data": LINKER_DATA}
    response = client.post("/api/v1/compendium", json=payload)
    assert response.status_code == 200, response.text
    stats = _statistics(response.json())
    assert stats["input_type"] == "linker_output" and stats["entities_count"] == 1
    assert stats["topic"] == "Optik"  # original_text is read as the topic, the labels stand in when it is empty
    assert "input_length" not in stats  # the old service left it out on this path


def test_options_without_a_counterpart_are_named_instead_of_ignored(client: TestClient) -> None:
    payload = {
        "input_type": "text",
        "text": "Optik",
        "config": {"length": 500, "enable_citations": False, "educational_mode": False},
    }
    body = client.post("/api/v1/compendium", json=payload).json()
    notes = _statistics(body)["notes"]
    assert any("enable_citations" in note for note in notes)
    assert any("educational_mode" in note for note in notes)
    assert any("length" in note for note in notes)  # clamped into the range of the new service
    assert _statistics(body)["citations_enabled"] is True  # the answer says what the text really is


def test_bad_requests_get_a_status_code_not_an_error_text(client: TestClient) -> None:
    assert client.post("/api/v1/compendium", json={"input_type": "text"}).status_code == 400
    assert client.post("/api/v1/compendium", json={"input_type": "linker_output"}).status_code == 400
    assert client.post("/api/v1/compendium", json={"input_type": "audio", "text": "x"}).status_code == 422
    english = {"input_type": "text", "text": "Optik", "config": {"language": "en"}}
    response = client.post("/api/v1/compendium", json=english)
    assert response.status_code == 422 and "Deutsch" in response.text
    unknown = {"input_type": "text", "text": "Xyzzyplomb"}
    assert client.post("/api/v1/compendium", json=unknown).status_code == 404


def test_pipeline_compendium_only_keeps_its_four_blocks(client: TestClient) -> None:
    payload = {"text": "Optik", "config": {"linker": {"MODE": "extract"}, "compendium": {"length": 6000}}}
    response = client.post("/api/v1/pipeline-compendium-only", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"original_text", "linker_output", "compendium_output", "pipeline_statistics"}
    assert body["original_text"] == "Optik"
    entities = body["linker_output"]["entities"]
    assert body["linker_output"]["original_text"] == "Optik" and entities
    first = entities[0]
    assert set(first) == {"entity", "details", "sources"}
    assert set(first["details"]) == {"typ", "citation"}
    wikipedia = first["sources"]["wikipedia"]
    assert wikipedia["status"] == "found" and wikipedia["label_de"] and wikipedia["extract"]
    assert wikipedia["url_de"].startswith("http")
    assert set(body["compendium_output"]) == {"markdown", "bibliography", "statistics"}
    statistics = body["pipeline_statistics"]
    assert set(statistics["processing_times"]) == {"linker", "compendium"}
    assert statistics["completed_steps"] == 2 and statistics["total_steps"] == 2 and statistics["errors"] == []
    assert statistics["total_processing_time"] >= 0


def test_the_new_options_of_the_compendium_config_are_accepted(client: TestClient) -> None:
    payload = {
        "text": "Optik",
        "config": {"compendium": {"template_id": "standard", "parts": ["world"], "extraction": "rule-based"}},
    }
    response = client.post("/api/v1/pipeline-compendium-only", json=payload)
    assert response.status_code == 200, response.text
    statistics = response.json()["compendium_output"]["statistics"]
    assert statistics["audit"]["template"] == "standard"


def test_the_pipeline_rejects_an_empty_text_and_an_unknown_topic(client: TestClient) -> None:
    assert client.post("/api/v1/pipeline-compendium-only", json={"text": ""}).status_code == 422
    assert client.post("/api/v1/pipeline-compendium-only", json={"text": "   "}).status_code == 400
    assert client.post("/api/v1/pipeline-compendium-only", json={"text": "Xyzzyplomb"}).status_code == 404


def test_a_linker_output_without_a_text_falls_back_to_its_first_label(client: TestClient) -> None:
    payload = {"input_type": "linker_output", "linker_data": {"entities": LINKER_DATA["entities"]}}
    body = client.post("/api/v1/compendium", json=payload).json()
    assert body["statistics"]["topic"] == "Optik" and body["statistics"]["entities_count"] == 1
