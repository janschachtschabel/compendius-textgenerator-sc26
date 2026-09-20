"""The example in /docs has to work: it is the first request most callers ever send.

A caller who opens the interactive documentation edits the body it shows. Without an example, Swagger builds
one from the schema alone, and the field names have to carry the whole explanation - which is how a caller ends
up sending the topic in the wrong field. So every endpoint a person starts with documents a request it takes.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

STARTING_POINTS = ["/api/v2/compendium", "/api/v2/knowledge"]


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def documented_example(spec: dict[str, Any], path: str) -> Any:
    """The first example of the request body, as /docs shows it; None when the endpoint documents none."""
    schema = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]
    name = str(schema.get("$ref", "")).rsplit("/", 1)[-1]
    examples = spec["components"]["schemas"].get(name, {}).get("examples") or []
    return examples[0] if examples else None


@pytest.mark.parametrize("path", STARTING_POINTS)
def test_the_documented_example_is_a_request_the_endpoint_takes(client: TestClient, path: str) -> None:
    example = documented_example(client.get("/openapi.json").json(), path)
    assert example is not None, f"{path} shows no example, so /docs invents one from the field names"
    response = client.post(path, json=example)
    assert response.status_code != 422, f"the example of {path} is refused: {response.text[:300]}"
