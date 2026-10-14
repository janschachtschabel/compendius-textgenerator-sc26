"""The OpenAPI document as a catalogue entry (D107): a display name and a text for end users, a German summary for
every operation, a description for every group, and no probe of the platform in it (Team 6, 2026-10-14)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

# FastAPI's own summary: the function name in title case ("List Templates", "Zim Sync Now")
GENERATED = re.compile("^[A-Z][a-z]+( [A-Z][a-z]+)*$")
PROBES = ("/health", "/ready", "/metrics")


@pytest.fixture(scope="module")
def schema(settings: Settings) -> dict[str, Any]:
    with TestClient(create_app(settings)) as client:
        return dict(client.get("/openapi.json").json())


def operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [(method, path, op) for path, ops in schema["paths"].items() for method, op in ops.items()]


def test_the_document_names_the_service_for_end_users(schema: dict[str, Any]) -> None:
    info = schema["info"]
    assert info["title"] == "Kompendiale Texte"
    assert "Thema" in info["summary"] and "Lehrpläne" in info["summary"] and len(info["summary"]) < 300


def test_the_probes_of_the_platform_stay_out_of_the_document_and_still_answer(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert not set(PROBES) & set(paths)
        assert client.get("/health").status_code == 200 and client.get("/ready").status_code == 200


def test_every_operation_has_a_summary_of_its_own(schema: dict[str, Any]) -> None:
    generated = [
        f"{method.upper()} {path}: {op.get('summary')}"
        for method, path, op in operations(schema)
        if not op.get("summary") or GENERATED.match(op["summary"])
    ]
    assert not generated, generated


def test_every_group_says_what_it_holds(schema: dict[str, Any]) -> None:
    described = {tag["name"] for tag in schema.get("tags", []) if tag.get("description")}
    used = {tag for _, _, op in operations(schema) for tag in op.get("tags", [])}
    assert used <= described, sorted(used - described)


BETRIEB = Path(__file__).resolve().parents[1] / "docs" / "betrieb.md"
DOCUMENT_PAGES = {"/openapi.json", "/docs", "/redoc"}  # public, but no operations of the API
# The review page, off in operation; its row in the section names it as a whole
REVIEW_PAGE = "/ui"


def internal_endpoints(settings: Settings) -> set[str]:
    """Every endpoint the service answers that its OpenAPI document leaves out, as "METHOD path"."""
    app = create_app(settings)
    found = set()
    for route in iter_route_contexts(app.routes):
        path = route.path or ""
        if path in DOCUMENT_PAGES or path.startswith(REVIEW_PAGE) or not route.methods:
            continue
        if getattr(route, "include_in_schema", True):
            continue
        found |= {f"{method} {route.path}" for method in route.methods if method != "HEAD"}
    return found


def test_the_internal_endpoints_are_out_of_the_document(schema: dict[str, Any]) -> None:
    """Jan, 2026-10-14: separate the endpoints for the public and their use from the internal ones for reporting and
    operation; the internal ones do not belong in the public description."""
    paths = set(schema["paths"])
    assert not paths & {"/health", "/ready", "/metrics", "/api/v2/zim/status", "/api/v2/lehrplan/status"}
    assert not any(tag.endswith("-admin") for _, _, op in operations(schema) for tag in op.get("tags", []))


def test_every_internal_endpoint_is_documented_in_the_repository(settings: Settings) -> None:
    """Jan, 2026-10-14: "ins repo gehören die endpunkte (interne) aber auch dokumentiert"."""
    text = BETRIEB.read_text(encoding="utf-8")
    section = text[text.index("## Erreichbarkeit") :]
    listed = section[: section.index("\n## ", 1)]  # the section alone: other sections name endpoints too
    internal = internal_endpoints(settings)
    assert {"GET /metrics", "POST /api/v2/zim/sync", "PUT /api/v2/templates/{template_id}"} <= internal
    missing = sorted(endpoint for endpoint in internal if f"`{endpoint}`" not in listed)
    assert not missing, f"not listed in docs/betrieb.md, Erreichbarkeit: {missing}"
