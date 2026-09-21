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


def _request_models(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every model a caller fills in, reached from the request bodies and followed into nested models."""
    components: dict[str, dict[str, Any]] = schema.get("components", {}).get("schemas", {})
    found: dict[str, dict[str, Any]] = {}

    def references(spec: dict[str, Any]) -> list[str]:
        names = []
        reference = spec.get("$ref", "")
        if reference.startswith("#/components/schemas/"):
            names.append(reference.rsplit("/", 1)[1])
        for key in ("items", "additionalProperties"):
            if isinstance(spec.get(key), dict):
                names.extend(references(spec[key]))
        for option in spec.get("anyOf", []) + spec.get("allOf", []):
            if isinstance(option, dict):
                names.extend(references(option))
        return names

    def walk(name: str) -> None:
        if name in found or name not in components:
            return
        found[name] = components[name]
        for spec in components[name].get("properties", {}).values():
            for nested in references(spec):
                walk(nested)

    for operations in schema.get("paths", {}).values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            for name in references(body):
                walk(name)
    return found


def test_every_field_a_caller_fills_in_explains_itself(client: TestClient) -> None:
    """A field without a description is a bare name and a type in /docs; the caller has to guess.

    This covers the models behind every request body, nested ones included - a template is written
    through PUT /api/v2/templates/{id}, so its slots, budgets and facet spec are caller-facing too.
    """
    schema = client.get("/openapi.json").json()
    models = _request_models(schema)
    assert models, "no request models found - the traversal is broken, not the schema"
    bare = [
        f"{name}.{field}"
        for name, model in sorted(models.items())
        for field, spec in sorted(model.get("properties", {}).items())
        if not spec.get("description")
    ]
    assert not bare, "request fields without a help text in /docs:\n  " + "\n  ".join(bare)
