"""The error answers, alike on every route and described in OpenAPI (audit 2026-09-27, AP-01)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

# The refusals each route can give, beside its success: 401 and 429 come with the API key and the rate limit, 413
# with a body; the rest from the route (docstrings of the routes, app.api.domain_errors)
PROFILE = {"401", "404", "422", "429", "502", "503"}
REFUSALS = {
    ("post", "/api/v2/compendium"): PROFILE | {"413"},
    ("post", "/api/v2/knowledge"): PROFILE | {"413"},
    ("post", "/api/v2/qa"): PROFILE | {"413"},
    ("post", "/api/v2/entities"): PROFILE | {"413"},
    ("get", "/api/v2/lehrplan/search"): PROFILE - {"502"},
    ("get", "/api/v2/nodes/{node_id}"): PROFILE,
    ("get", "/api/v2/collections/{collection_id}/overview"): PROFILE,
    ("get", "/api/v2/templates/{template_id}"): {"404"},
    ("put", "/api/v2/templates/{template_id}"): {"403", "404", "409", "413", "422", "429"},
    ("delete", "/api/v2/templates/{template_id}"): {"403", "404", "409", "429"},
    ("get", "/api/v2/zim/catalog"): {"403", "404", "429", "502"},
    ("delete", "/api/v2/zim/{file_name}"): {"400", "403", "404", "409", "429"},
    ("post", "/api/v2/zim/sync"): {"403", "404", "429"},
    ("post", "/api/v2/lehrplan/harvest"): {"403", "404", "429"},
}


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def admin_client(settings: Settings) -> TestClient:
    enabled = settings.model_copy(update={"admin_token": "a" * 32})
    return TestClient(create_app(enabled))


def test_a_validator_answers_in_its_own_words(client: TestClient) -> None:
    """pydantic put an English "Value error, " before the German reason and an empty ``ctx`` beside it."""
    response = client.post("/api/v2/compendium", json={})
    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["type"] == "value_error"
    assert error["msg"] == "topic, collection_id oder node_id ist erforderlich"
    assert "ctx" not in error


@pytest.mark.parametrize("path", ["/api/v2/nodes/kaputt", "/api/v2/collections/kaputt/overview"])
def test_a_broken_node_id_is_the_same_422_on_every_route(client: TestClient, path: str) -> None:
    """The collection route checked the id itself and answered text, or a 503 without a repository before it looked;
    the node route answered the list of validation."""
    response = client.get(path)
    assert response.status_code == 422, response.text
    [error] = response.json()["detail"]
    assert error["type"] == "string_pattern_mismatch"
    assert error["loc"][0] == "path"


def test_every_route_describes_the_refusals_it_gives(admin_client: TestClient) -> None:
    """OpenAPI knew only 200 and 422, though routes answer 401, 404, 409, 413, 429, 502 and 503 as well."""
    paths = admin_client.get("/openapi.json").json()["paths"]
    for (method, path), refusals in REFUSALS.items():
        responses = paths[path][method]["responses"]
        assert refusals <= set(responses), (method, path, sorted(refusals - set(responses)))
        for status in refusals:
            answer = responses[status]
            assert answer["description"], (method, path, status)
            assert "application/json" in answer.get("content", {}), (method, path, status)


def test_the_error_model_names_the_three_shapes_of_detail(admin_client: TestClient) -> None:
    """A refusal is text, a 422 of validation a list, the 404 of a topic an object with the resolution."""
    schemas = admin_client.get("/openapi.json").json()["components"]["schemas"]
    assert schemas["Refusal"]["properties"]["detail"]["type"] == "string"
    assert {"$ref": "#/components/schemas/TopicMissing"} in schemas["NotFound"]["properties"]["detail"]["anyOf"]
    invalid = schemas["Invalid"]["properties"]["detail"]["anyOf"]
    assert {"type": "array", "items": {"$ref": "#/components/schemas/Problem"}} in invalid
