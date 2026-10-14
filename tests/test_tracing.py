"""Trace headers (D108): read where a request comes in, named in the JSON log line, sent on to the b-api and to
edu-sharing - unchanged, or not at all when a value carries signs no trace id has."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.api.request_log import RequestLog
from app.concurrency import map_in_threads
from app.llm.client import BApiClient
from app.logging import _JsonFormatter
from app.sources.wlo.client import EduSharingClient
from app.tracing import _trace, outgoing_headers, take_trace_headers, trace_id
from tests.test_llm_client import BASE, KEY, MESSAGES, FakeBApi

TRACED = [
    (b"X-Client-Trace-Id", b"client-4711"),
    (b"x-b3-traceid", b"80f198ee56343ba864fe8b2a57d3eff7"),
    (b"x-b3-spanid", b"e457b5a2e4d86bd1"),
    (b"x-b3-sampled", b"1"),
]


@pytest.fixture(autouse=True)
def outside_a_request() -> Any:
    """Each test in a context of its own: the trace of one must reach no other test (review of D108)."""
    token = _trace.set({})
    yield
    _trace.reset(token)


def test_the_trace_headers_of_a_request_are_kept_as_they_came() -> None:
    found = take_trace_headers([*TRACED, (b"accept", b"*/*")], "req-1")

    assert found == {name.decode().lower(): value.decode() for name, value in TRACED}
    assert outgoing_headers() == {**found, "X-Request-ID": "req-1"}


@pytest.mark.parametrize("value", [b"two words", b"a" * 300, b"line" + bytes([10]) + b"break", b""])
def test_a_value_no_trace_id_has_is_dropped_not_changed(value: bytes) -> None:
    assert take_trace_headers([(b"x-client-trace-id", value)], "req-1") == {}
    assert outgoing_headers() == {"X-Request-ID": "req-1"}


def test_the_trace_of_a_line_is_the_clients_else_the_b3_trace() -> None:
    take_trace_headers(TRACED, "req-1")
    assert trace_id() == "client-4711"
    take_trace_headers(TRACED[1:], "req-1")
    assert trace_id() == "80f198ee56343ba864fe8b2a57d3eff7"
    take_trace_headers([(b"b3", b"80f198ee56343ba8-e457b5a2e4d86bd1-1")], "req-1")
    assert trace_id() == "80f198ee56343ba8"
    take_trace_headers([(b"b3", b"0")], "req-1")
    assert trace_id() is None, "a sampling decision alone names no trace"
    take_trace_headers([(b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")], "req-1")
    assert trace_id() == "4bf92f3577b34da6a3ce929d0e0e4736"
    take_trace_headers([], "req-1")
    assert trace_id() is None


def test_a_json_line_names_the_trace() -> None:
    take_trace_headers(TRACED, "req-1")
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello", None, None)
    assert json.loads(_JsonFormatter().format(record))["trace_id"] == "client-4711"
    take_trace_headers([], "req-1")
    assert "trace_id" not in json.loads(_JsonFormatter().format(record))


def test_a_call_to_the_b_api_carries_the_trace_on() -> None:
    fake = FakeBApi()
    client = BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))
    take_trace_headers(TRACED, "req-1")

    client.chat(MESSAGES, max_output_tokens=10)

    sent = fake.requests[0].headers
    assert sent["x-client-trace-id"] == "client-4711" and sent["x-b3-spanid"] == "e457b5a2e4d86bd1"
    assert sent["x-request-id"] == "req-1" and sent["x-api-key"] == KEY


def test_a_read_of_the_repository_carries_the_trace_on() -> None:
    seen: list[httpx.Request] = []

    def repository(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Licht"})

    client = EduSharingClient(
        "https://repository.example.org/edu-sharing/rest", transport=httpx.MockTransport(repository)
    )
    take_trace_headers(TRACED, "req-1")

    client.text_content("9e7ae956-e9df-430f-bace-f3db4b910013")

    assert seen[0].headers["x-client-trace-id"] == "client-4711" and seen[0].headers["x-request-id"] == "req-1"


def test_the_request_log_takes_the_trace_for_the_whole_request() -> None:
    """The middleware that names a request takes its trace too, so every call made for it carries both."""

    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"outgoing": outgoing_headers(), "trace": trace_id()})

    app = RequestLog(Starlette(routes=[Route("/", endpoint)]), routes=[])
    with TestClient(app) as client:
        answer = client.get("/", headers={"x-client-trace-id": "client-4711", "x-request-id": "req-9"})

    assert answer.json() == {
        "outgoing": {"x-client-trace-id": "client-4711", "X-Request-ID": "req-9"},
        "trace": "client-4711",
    }
    assert "x-client-trace-id" not in answer.headers, "the trace goes on to the services called, not back"


def test_a_tracestate_goes_on_as_the_w3c_allows_it() -> None:
    """Spaces after a comma, vendor keys with *, values with ~ and up to 512 signs, and repeated headers joined."""
    long_state = "vendor=" + "a" * 500
    found = take_trace_headers(
        [(b"tracestate", b"rojo=00f067aa0ba902b7, congo=t61rcWkgMzE"), (b"tracestate", b"tenant*v=x~y")], "req-1"
    )
    assert found["tracestate"] == "rojo=00f067aa0ba902b7, congo=t61rcWkgMzE,tenant*v=x~y"
    assert take_trace_headers([(b"tracestate", long_state.encode())], "req-1")["tracestate"] == long_state
    assert take_trace_headers([(b"tracestate", b"a=" + bytes([1]) + b"b")], "req-1") == {}


def test_the_threads_of_a_request_carry_its_trace() -> None:
    """The LLM stages call the b-api from pool threads (app/concurrency.py): the trace goes with them."""
    take_trace_headers(TRACED, "req-1")

    seen = map_in_threads(lambda _: outgoing_headers(), [1, 2, 3], 3)

    assert all(headers["x-client-trace-id"] == "client-4711" for headers in seen)
