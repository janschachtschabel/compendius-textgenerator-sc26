"""Rate limit, key and admin token are asked before the body is read, and each route bounds its own body (audit
2026-09-28, SE-18).

FastAPI reads and parses a body before any dependency runs. Every body up to 13 MB, the size existing_markdown
needs, was parsed before the key and the rate limit were asked: 13 MB of ``[{},...]`` made 312 MB of Python objects,
and the 401 without a key came after 450 to 590 ms instead of 49 ms. The requests here go straight to the ASGI app,
so the test sees whether the body was read at all.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.body_limit import LARGE_BODY_BYTES
from app.api.gates import EARLY, GatedRoute
from app.main import create_app
from app.settings import Settings

KEY = "k" * 32
TOKEN = "t" * 32
QA_BODY = b'{"text": "Die Optik ist die Lehre vom Licht und seiner Ausbreitung."}'


def send(
    app: FastAPI, method: str, path: str, body: bytes, headers: Mapping[str, str] | None = None
) -> tuple[int, int]:
    """The status of the answer, and how often the app asked for a piece of the body."""
    pieces = [body[start : start + 65_536] for start in range(0, len(body), 65_536)] or [b""]
    reads = 0
    status = 0

    async def receive() -> dict[str, object]:
        nonlocal reads
        reads += 1
        if pieces:
            piece = pieces.pop(0)
            return {"type": "http.request", "body": piece, "more_body": bool(pieces)}
        return {"type": "http.disconnect"}

    async def answer(message: Mapping[str, object]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(str(message["status"]))

    head = {"content-type": "application/json", "content-length": str(len(body)), **(headers or {})}
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(name.lower().encode(), value.encode()) for name, value in head.items()],
        "client": ("198.51.100.7", 40_000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, answer))
    return status, reads


def test_a_request_without_a_key_is_refused_before_its_body_is_read(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"api_keys": KEY}))

    assert send(app, "POST", "/api/v2/qa", QA_BODY) == (401, 0)
    assert send(app, "POST", "/api/v2/compendium", b'{"topic": "Optik"}', {"x-api-key": "falsch" * 6}) == (401, 0)


def test_a_client_over_its_limit_is_refused_before_its_body_is_read(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"rate_limit": 1}))

    first, _ = send(app, "POST", "/api/v2/qa", QA_BODY)
    refused = send(app, "POST", "/api/v2/qa", QA_BODY)

    assert first != 429
    assert refused == (429, 0)


def test_an_admin_route_is_refused_before_its_body_is_read(settings: Settings) -> None:
    template = b'{"id": "eigenes", "name": "Eigenes"}'
    closed = create_app(settings.model_copy(update={"admin_token": ""}))
    guarded = create_app(settings.model_copy(update={"admin_token": TOKEN}))

    assert send(closed, "PUT", "/api/v2/templates/eigenes", template) == (404, 0)
    assert send(guarded, "PUT", "/api/v2/templates/eigenes", template) == (403, 0)
    assert send(guarded, "PUT", "/api/v2/templates/eigenes", template, {"x-admin-token": "x" * 32}) == (403, 0)


def test_a_request_counts_once_although_its_gates_run_first(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"rate_limit": 2}))

    statuses = [send(app, "POST", "/api/v2/qa", QA_BODY)[0] for _ in range(3)]

    assert statuses[:2] == [200, 200]
    assert statuses[2] == 429


def test_a_body_is_bounded_by_its_route(settings: Settings) -> None:
    app = create_app(settings)
    two_mb = b" " * 2_000_000

    assert send(app, "POST", "/api/v2/qa", b" " * (settings.request_body_max_bytes + 1))[0] == 413
    assert send(app, "POST", "/api/v2/entities", two_mb)[0] == 413
    assert send(app, "POST", "/api/v2/knowledge", two_mb)[0] == 413
    # existing_markdown and a whole template keep their room
    assert send(app, "POST", "/api/v2/compendium", two_mb)[0] == 422
    assert send(app, "PUT", "/api/v2/templates/eigenes", two_mb)[0] != 413


def test_the_bound_of_the_small_bodies_is_a_setting(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"request_body_max_bytes": 50}))

    assert send(app, "POST", "/api/v2/qa", QA_BODY)[0] == 413
    assert send(app, "POST", "/api/v2/compendium", QA_BODY)[0] != 413  # the large bodies keep their own bound


def test_the_default_leaves_room_for_the_largest_small_field(settings: Settings) -> None:
    # The text of /qa and /entities takes 50,000 characters, each a six-byte JSON escape at worst
    assert settings.request_body_max_bytes >= 6 * 50_000 + 10_000
    assert LARGE_BODY_BYTES >= 6 * 2_000_000


def api_routes(routes: list[Any]) -> Iterator[APIRoute]:
    """Every route of the app; FastAPI 0.141 keeps an included router's routes behind a wrapper of its own."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif (router := getattr(route, "original_router", None)) is not None:
            yield from api_routes(router.routes)


def test_every_route_with_a_gate_asks_it_before_the_body(settings: Settings) -> None:
    gated = [
        route
        for route in api_routes(create_app(settings).routes)
        if any(dependency.call in EARLY for dependency in route.dependant.dependencies)
    ]

    assert len(gated) == 14  # seven profile and seven admin routes; an empty list would pass the check below unseen
    assert [route.path for route in gated if not isinstance(route, GatedRoute)] == []
