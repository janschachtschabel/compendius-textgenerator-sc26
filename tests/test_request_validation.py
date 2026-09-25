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
