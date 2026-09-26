"""/docs explains every parameter and value, says what each profile does per endpoint, and shows examples from the
shortest request to one with every field.

Jan, 2026-09-26: the help text of every endpoint describes all its parameters and the values they take, says what
happens there in each profile, and the examples go from a simple request to a complex one with all parameters.
Checked on 2026-09-26: seven parameters had no help text, /knowledge named two of the four profiles and /compendium
three, the curriculum search took none, and no example of any endpoint used every field.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

from app.domain.requests import Preset
from app.main import create_app
from app.settings import Settings
from app.templates.schema import Template
from tests.test_docs_examples import _request_models

PROFILES = get_args(Preset)
# Endpoints whose work no profile changes; their text has to say so, so nobody looks for a preset there
WITHOUT_PROFILE = [
    "POST /api/v2/entities",
    "GET /api/v2/nodes/{node_id}",
    "GET /api/v2/collections/{collection_id}/overview",
]
# The server sets these; an example that sends them would teach the caller to
SERVER_SET = {"Template": {"version", "builtin"}}


@pytest.fixture(scope="module")
def spec(settings: Settings) -> dict[str, Any]:
    schema: dict[str, Any] = TestClient(create_app(settings)).get("/openapi.json").json()
    return schema


def operations(spec: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for path, methods in sorted(spec["paths"].items()):
        for method, operation in methods.items():
            if method in ("get", "post", "put", "delete", "patch"):
                yield f"{method.upper()} {path}", operation


def enum_of(schema: dict[str, Any]) -> list[str]:
    """The values a parameter or field allows: plain, optional (anyOf with null) or as the items of a list."""
    for option in [schema, *schema.get("anyOf", [])]:
        for candidate in (option, option.get("items", {})):
            if isinstance(candidate, dict) and "enum" in candidate:
                return [str(value) for value in candidate["enum"]]
    return []


def body_model(spec: dict[str, Any], operation: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    content = operation.get("requestBody", {}).get("content", {}).get("application/json")
    if not content:
        return None
    name = str(content["schema"].get("$ref", "")).rsplit("/", 1)[-1]
    return name, spec["components"]["schemas"][name]


def named_examples(operation: dict[str, Any]) -> list[dict[str, Any]]:
    content = operation["requestBody"]["content"]["application/json"]
    return [entry["value"] for entry in (content.get("examples") or {}).values()]


def test_every_parameter_says_what_it_takes(spec: dict[str, Any]) -> None:
    bare = [
        f"{name}: {parameter['in']} {parameter['name']}"
        for name, operation in operations(spec)
        for parameter in operation.get("parameters", [])
        if len((parameter.get("description") or "").strip()) < 20
    ]
    assert not bare, "parameters without a help text in /docs:\n  " + "\n  ".join(bare)


def test_every_value_a_parameter_or_field_takes_is_explained(spec: dict[str, Any]) -> None:
    unexplained = [
        f"{name}: {parameter['name']} {missing}"
        for name, operation in operations(spec)
        for parameter in operation.get("parameters", [])
        if (missing := [v for v in enum_of(parameter["schema"]) if v not in (parameter.get("description") or "")])
    ]
    unexplained += [
        f"{model}.{field}: {missing}"
        for model, schema in sorted(_request_models(spec).items())
        for field, prop in sorted(schema.get("properties", {}).items())
        if (missing := [v for v in enum_of(prop) if v not in (prop.get("description") or "")])
    ]
    assert not unexplained, "values /docs lists but does not explain:\n  " + "\n  ".join(unexplained)


def test_an_endpoint_that_takes_a_profile_says_what_each_one_does_there(spec: dict[str, Any]) -> None:
    profiled = []
    for name, operation in operations(spec):
        body = body_model(spec, operation)
        fields = body[1].get("properties", {}) if body else {}
        if "preset" in fields or any(p["name"] == "preset" for p in operation.get("parameters", [])):
            profiled.append(name)
            missing = [profile for profile in PROFILES if profile not in operation.get("description", "")]
            assert not missing, f"{name} does not say what {missing} do there"
    assert {
        "POST /api/v2/compendium",
        "POST /api/v2/knowledge",
        "POST /api/v2/qa",
        "GET /api/v2/lehrplan/search",
    } <= set(profiled)


@pytest.mark.parametrize("name", WITHOUT_PROFILE)
def test_an_endpoint_without_a_profile_says_so(spec: dict[str, Any], name: str) -> None:
    operation = dict(operations(spec))[name]
    assert "preset" not in {p["name"] for p in operation.get("parameters", [])}
    assert "profile" in operation["description"].lower(), f"{name} does not say that no profile changes it"


def test_the_examples_run_from_the_shortest_request_to_every_field(spec: dict[str, Any]) -> None:
    for name, operation in operations(spec):
        body = body_model(spec, operation)
        if body is None:
            continue
        model, schema = body
        examples = named_examples(operation)
        assert len(examples) >= 2, f"{name} offers {len(examples)} examples"
        sizes = [len(example) for example in examples]
        assert sizes[0] == min(sizes), f"{name}: the first example is not the shortest request"
        used = {field for example in examples for field in example}
        missing = set(schema["properties"]) - used - SERVER_SET.get(model, set())
        assert not missing, f"{name}: no example sets {sorted(missing)}"


def test_the_template_examples_are_templates_the_service_takes(spec: dict[str, Any]) -> None:
    for example in named_examples(spec["paths"]["/api/v2/templates/{template_id}"]["put"]):
        assert Template.model_validate(example).id == example["id"]


def test_a_get_endpoint_shows_calls_with_every_query_parameter(spec: dict[str, Any]) -> None:
    for name, operation in operations(spec):
        query = [p["name"] for p in operation.get("parameters", []) if p["in"] == "query"]
        if not name.startswith("GET") or not query:
            continue
        missing = [parameter for parameter in query if f"{parameter}=" not in operation["description"]]
        assert not missing, f"{name}: no example call in its description sets {missing}"


def test_every_path_parameter_of_a_public_endpoint_offers_an_example(spec: dict[str, Any]) -> None:
    for name, operation in operations(spec):
        parameters = operation.get("parameters", [])
        if any(p["in"] == "header" for p in parameters):  # admin endpoints: X-Admin-Token
            continue
        bare = [p["name"] for p in parameters if p["in"] == "path" and not p.get("examples")]
        assert not bare, f"{name}: Swagger offers no example for {bare}"
