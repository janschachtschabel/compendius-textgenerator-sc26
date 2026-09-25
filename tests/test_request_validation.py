"""A field the service does not know is a 422, not a silent miss (review of 2026-09-25, decision paper item 8).

A typo such as ``topik`` or ``subjekt`` used to vanish: the request ran without it and the answer looked right.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v2/compendium", {"topic": "Optik"}),
        ("/api/v2/knowledge", {"topic": "Optik"}),
        ("/api/v2/qa", {"text": "Die Optik ist die Lehre vom Licht und seiner Ausbreitung."}),
        ("/api/v2/entities", {"text": "Ernst Abbe entwickelte in Jena das Lichtmikroskop."}),
    ],
)
def test_an_unknown_field_is_a_422_that_names_it(client: TestClient, path: str, body: dict[str, Any]) -> None:
    answer = client.post(path, json={**body, "topik": "Optik"})
    assert answer.status_code == 422, answer.text
    assert [error["loc"] for error in answer.json()["detail"]] == [["body", "topik"]]


@pytest.mark.parametrize("path", ["/api/v2/compendium", "/api/v2/knowledge", "/api/v2/qa"])
def test_an_unknown_subject_is_a_422_that_lists_the_known_ones(client: TestClient, path: str) -> None:
    """Part 2 searched every subject and the article choice went on without one, and nothing said so."""
    answer = client.post(path, json={"topic": "Optik", "subject": "Pysik"})
    assert answer.status_code == 422, answer.text
    assert "Pysik" in answer.json()["detail"] and "Physik" in answer.json()["detail"]


def test_blocks_to_make_anew_need_the_earlier_text_and_names_the_template_knows(client: TestClient) -> None:
    alone = client.post("/api/v2/compendium", json={"topic": "Optik", "regenerate_sections": ["sc26_3"]})
    assert alone.status_code == 422 and "existing_markdown" in alone.text
    body = {"topic": "Optik", "existing_markdown": "# Optik", "regenerate_sections": ["themendefinition"]}
    unknown = client.post("/api/v2/compendium", json=body)
    assert unknown.status_code == 422, unknown.text
    assert "themendefinition" in unknown.json()["detail"] and "sc26_1" in unknown.json()["detail"]


def test_a_knowledge_collection_without_part_1_is_a_422(client: TestClient) -> None:
    """Its materials only feed part 1; without it they were quietly not read."""
    body = {"topic": "Optik", "knowledge_collection_id": "9e7ae956-e9df-430f-bace-f3db4b910013", "parts": ["curricula"]}
    answer = client.post("/api/v2/compendium", json=body)
    assert answer.status_code == 422 and "knowledge_collection_id" in answer.text
