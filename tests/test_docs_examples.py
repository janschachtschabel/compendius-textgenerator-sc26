"""The example in /docs has to work: it is the first request most callers ever send.

A caller who opens the interactive documentation edits the body it shows. Without an example, Swagger builds
one from the schema alone, and the field names have to carry the whole explanation - which is how a caller ends
up sending the topic in the wrong field. So every endpoint a person starts with documents a request it takes.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.test_wlo_client import BASE, FakeRepository

STARTING_POINTS = ["/api/v2/compendium", "/api/v2/knowledge", "/api/v2/qa", "/api/v2/entities"]
STAGING = "https://repository.staging.openeduhub.net/edu-sharing/rest"


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    # The part 3 example names a collection of the staging repository, which the default settings point at. The fake
    # answers for the same collection, so the example runs offline instead of opening a connection to staging.
    app = create_app(settings)
    repository = EduSharingClient(BASE, transport=httpx.MockTransport(FakeRepository()), page_size=10)
    builder = CollectionBuilder(client=repository, cache=None)
    app.state.collections = builder
    app.state.service.collections = builder
    return TestClient(app)


def documented_examples(spec: dict[str, Any], path: str) -> dict[str, Any]:
    """Every example of the request body, by name, as /docs offers them.

    Named examples live on the media type and Swagger shows them in a chooser; a plain list on the
    schema is shown as the one body it prefills. Both are read, so neither form goes unchecked.
    """
    content = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]
    named = content.get("examples") or {}
    if named:
        return {name: entry.get("value") for name, entry in named.items()}
    name = str(content["schema"].get("$ref", "")).rsplit("/", 1)[-1]
    listed = spec["components"]["schemas"].get(name, {}).get("examples") or []
    return {f"example {index}": body for index, body in enumerate(listed)}


@pytest.mark.parametrize("path", STARTING_POINTS)
def test_every_documented_example_is_a_request_the_endpoint_takes(client: TestClient, path: str) -> None:
    examples = documented_examples(client.get("/openapi.json").json(), path)
    assert examples, f"{path} shows no example, so /docs invents one from the field names"
    for name, example in examples.items():
        response = client.post(path, json=example)
        assert response.status_code != 422, f"example {name!r} of {path} is refused: {response.text[:300]}"


@pytest.mark.parametrize("path", STARTING_POINTS)
def test_an_endpoint_a_caller_starts_with_shows_its_switches_too(client: TestClient, path: str) -> None:
    """One example is the shortest request that works; a second one has to show what else there is.

    The minimal body is what a caller should send first, and it deliberately names three fields. That
    is also why the switches are invisible in the box Swagger prefills - so a second example carries
    them, and Swagger offers both by name.
    """
    examples = documented_examples(client.get("/openapi.json").json(), path)
    assert len(examples) >= 2, f"{path} offers only {sorted(examples)}; the switches stay invisible"
    sizes = sorted(len(body) for body in examples.values())
    assert sizes[-1] > sizes[0], "the second example has to carry more than the shortest one"


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


def test_every_endpoint_says_what_it_does(client: TestClient) -> None:
    """An endpoint without a description is a bare path and a verb in /docs.

    The description comes from the handler's docstring, so a missing one is a handler nobody wrote a
    sentence for. Measured on 2026-09-21: six of twenty-one had none.
    """
    schema = client.get("/openapi.json").json()
    bare = [
        f"{method.upper()} {path}"
        for path, operations in sorted(schema.get("paths", {}).items())
        for method, operation in operations.items()
        if method in ("get", "post", "put", "delete", "patch") and not (operation.get("description") or "").strip()
    ]
    assert not bare, "endpoints without a description in /docs:\n  " + "\n  ".join(bare)


@pytest.mark.parametrize("path", STARTING_POINTS)
def test_the_templates_name_a_node_of_the_staging_repository(client: TestClient, path: str) -> None:
    """Named, so Swagger offers them in its chooser; a second entry of a plain list on the schema is never shown."""
    content = client.get("/openapi.json").json()["paths"][path]["post"]["requestBody"]["content"]["application/json"]
    named = [entry["value"] for entry in (content.get("examples") or {}).values()]
    assert any(body.get("node_id") and body.get("repository", STAGING) == STAGING for body in named), path


def test_the_node_preview_offers_staging_templates(client: TestClient) -> None:
    """Parameters take their templates from ``examples`` on the parameter; Swagger ignores a list on the schema."""
    spec = client.get("/openapi.json").json()
    parameters = {entry["name"]: entry for entry in spec["paths"]["/api/v2/nodes/{node_id}"]["get"]["parameters"]}
    node_ids = [entry["value"] for entry in parameters["node_id"].get("examples", {}).values()]
    repositories = [entry["value"] for entry in parameters["repository"].get("examples", {}).values()]
    assert "ac66224b-42b0-4676-a53d-71b058dc780b" in node_ids
    assert STAGING in repositories
