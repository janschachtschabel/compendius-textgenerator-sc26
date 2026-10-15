"""Behind a proxy with a prefix (UVICORN_ROOT_PATH) uvicorn puts the root path in front of every path; the router takes
it off. The middlewares that look at the path before the router must do the same (audit 2026-10-15). The scopes are
uvicorn's: TestClient leaves the root path out of the path."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import MutableMapping
from typing import Any

import pytest
from starlette.types import Receive, Scope, Send

from app.api.body_limit import LARGE_BODY_BYTES, BodySizeLimit
from app.api.request_log import RequestLog

ROOT = "/kompendium"


def scope(method: str, path: str, *, length: int = 0) -> dict[str, Any]:
    headers = [(b"content-length", str(length).encode())] if length else []
    return {
        "type": "http", "method": method, "path": ROOT + path, "root_path": ROOT, "raw_path": (ROOT + path).encode(),
        "server": ("10.0.0.5", 8000), "headers": headers, "query_string": b"", "client": ("10.0.0.9", 50000),
    }  # fmt: skip


def run(app: Any, request: dict[str, Any]) -> list[MutableMapping[str, Any]]:
    sent: list[MutableMapping[str, Any]] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(app(request, receive, send))
    return sent


async def ok(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


def test_the_large_body_of_a_compendium_passes_behind_a_prefix() -> None:
    """An existing_markdown over the small bound was a 413 behind a prefix and passed without one."""
    sent = run(BodySizeLimit(ok, max_bytes=1_000_000), scope("POST", "/api/v2/compendium", length=2_000_000))
    assert sent[0]["status"] == 200


def test_the_bound_still_holds_behind_a_prefix() -> None:
    request = scope("POST", "/api/v2/compendium", length=LARGE_BODY_BYTES + 1)
    assert run(BodySizeLimit(ok, max_bytes=1_000_000), request)[0]["status"] == 413


@pytest.mark.parametrize("path", ["/health", "/ready", "/metrics"])
def test_an_answering_probe_writes_no_line_behind_a_prefix(path: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.request_log"):
        run(RequestLog(ok, routes=[]), scope("GET", path))
    assert not [record for record in caplog.records if path in record.getMessage()]
