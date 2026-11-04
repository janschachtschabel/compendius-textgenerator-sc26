"""Tracing in B3 (D108, D115): a span of the service per request, the child of the caller's or a new trace; its ids in
the JSON log line and in the headers of every call to the b-api and edu-sharing, one header per value; a value no
trace id has is dropped, not changed."""

from __future__ import annotations

import json
import logging
import re
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
from app.tracing import (
    _trace,
    _trace_headers,
    client_trace_id,
    configure,
    end_request,
    outgoing_headers,
    service_name,
    span_id,
    start_request,
    trace_id,
)
from tests.test_llm_client import BASE, KEY, MESSAGES, FakeBApi

TRACE = "80f198ee56343ba864fe8b2a57d3eff7"
CALLER_SPAN = "e457b5a2e4d86bd1"
TRACED = [
    (b"X-Client-Trace-Id", b"client-4711"),
    (b"x-b3-traceid", TRACE.encode()),
    (b"x-b3-spanid", CALLER_SPAN.encode()),
    (b"x-b3-sampled", b"1"),
]
HEX32 = re.compile("[0-9a-f]{32}")
HEX16 = re.compile("[0-9a-f]{16}")


@pytest.fixture(autouse=True)
def outside_a_request() -> Any:
    """Each test in a context of its own: the trace of one must reach no other test (review of D108)."""
    token = _trace.set(None)
    yield
    _trace.reset(token)


def test_the_span_of_the_service_is_the_child_of_the_callers_and_goes_on_as_b3_headers() -> None:
    start_request([*TRACED, (b"accept", b"*/*")], "req-1", "POST")

    sent = outgoing_headers()

    assert trace_id() == TRACE and HEX16.fullmatch(span_id() or "")
    assert span_id() != CALLER_SPAN, "the service's own span, not the caller's"
    assert sent["x-b3-traceid"] == TRACE and sent["x-b3-spanid"] == span_id() and sent["x-b3-sampled"] == "1"
    assert sent["traceparent"] == f"00-{TRACE}-{span_id()}-01", "W3C beside B3, the same trace"
    assert sent["x-client-trace-id"] == "client-4711" and sent["X-Request-ID"] == "req-1"
    assert "b3" not in sent, "one header per value (B3 multi)"


def test_without_a_trace_the_service_starts_one() -> None:
    start_request([], "req-1", "GET")
    assert HEX32.fullmatch(trace_id() or "") and HEX16.fullmatch(span_id() or "")
    assert outgoing_headers()["x-b3-traceid"] == trace_id()


def test_the_single_header_form_and_w3c_are_read_and_b3_wins() -> None:
    start_request([(b"b3", f"{TRACE}-{CALLER_SPAN}-1".encode())], "req-1", "GET")
    assert trace_id() == TRACE
    start_request([(b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")], "req-1", "GET")
    assert trace_id() == "4bf92f3577b34da6a3ce929d0e0e4736"
    both = [(b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"), *TRACED[1:]]
    start_request(both, "req-1", "GET")
    assert trace_id() == TRACE


def test_a_64_bit_trace_stays_one_in_the_log_and_on_the_way() -> None:
    start_request([(b"x-b3-traceid", b"80f198ee56343ba8"), (b"x-b3-spanid", CALLER_SPAN.encode())], "req-1", "GET")
    assert trace_id() == "80f198ee56343ba8"
    assert outgoing_headers()["x-b3-traceid"] == "80f198ee56343ba8"


def test_a_trace_id_without_a_span_id_is_joined_not_dropped() -> None:
    start_request([(b"x-b3-traceid", TRACE.encode())], "req-1", "GET")
    assert trace_id() == TRACE


def test_a_trace_not_sampled_keeps_its_ids_and_goes_on_unsampled() -> None:
    start_request([*TRACED[1:3], (b"x-b3-sampled", b"0")], "req-1", "GET")
    assert trace_id() == TRACE
    assert outgoing_headers()["x-b3-sampled"] == "0"


@pytest.mark.parametrize("value", [b"two words", b"a" * 300, b"line" + bytes([10]) + b"break", b""])
def test_a_value_no_trace_id_has_is_dropped_not_changed(value: bytes) -> None:
    start_request([(b"x-client-trace-id", value)], "req-1", "GET")
    assert client_trace_id() is None
    assert "x-client-trace-id" not in outgoing_headers()


def test_a_probe_traces_nothing_and_names_its_request_only() -> None:
    start_request(TRACED, "req-1", "GET", traced=False)
    assert trace_id() is None and span_id() is None
    assert outgoing_headers() == {"x-client-trace-id": "client-4711", "X-Request-ID": "req-1"}


def test_a_json_line_names_service_trace_span_and_client_trace() -> None:
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello", None, None)
    outside = json.loads(_JsonFormatter().format(record))
    assert outside["service"] == service_name() and "trace_id" not in outside

    start_request(TRACED, "req-1", "GET")
    line = json.loads(_JsonFormatter().format(record))

    assert (line["trace_id"], line["span_id"], line["client_trace_id"]) == (TRACE, span_id(), "client-4711")


def test_the_service_name_comes_from_the_settings() -> None:
    configure("kompendium-test")
    try:
        record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello", None, None)
        assert json.loads(_JsonFormatter().format(record))["service"] == "kompendium-test"
    finally:
        configure()


def test_a_call_to_the_b_api_carries_the_trace_on() -> None:
    fake = FakeBApi()
    client = BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))
    start_request(TRACED, "req-1", "POST")

    client.chat(MESSAGES, max_output_tokens=10)

    sent = fake.requests[0].headers
    assert sent["x-b3-traceid"] == TRACE and sent["x-b3-spanid"] == span_id()
    assert sent["x-client-trace-id"] == "client-4711" and sent["x-request-id"] == "req-1" and sent["x-api-key"] == KEY


def test_a_read_of_the_repository_carries_the_trace_on() -> None:
    seen: list[httpx.Request] = []

    def repository(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "Licht"})

    client = EduSharingClient(
        "https://repository.example.org/edu-sharing/rest", transport=httpx.MockTransport(repository)
    )
    start_request(TRACED, "req-1", "GET")

    client.text_content("9e7ae956-e9df-430f-bace-f3db4b910013")

    assert seen[0].headers["x-b3-traceid"] == TRACE and seen[0].headers["x-request-id"] == "req-1"


def test_the_request_log_traces_the_whole_request_and_names_the_trace_in_the_answer() -> None:
    """The middleware that names a request opens its span, so every call made for it carries the trace; the answer
    names the trace, so a caller can ask about the request by it."""

    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"outgoing": outgoing_headers(), "trace": trace_id()})

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"trace": trace_id()})

    app = RequestLog(Starlette(routes=[Route("/", endpoint), Route("/health", health)]), routes=[])
    with TestClient(app) as client:
        answer = client.get("/", headers={"x-b3-traceid": TRACE, "x-b3-spanid": CALLER_SPAN, "x-request-id": "req-9"})
        probe = client.get("/health", headers={"x-b3-traceid": TRACE, "x-b3-spanid": CALLER_SPAN})

    assert answer.json()["trace"] == TRACE and answer.json()["outgoing"]["X-Request-ID"] == "req-9"
    assert answer.headers["x-b3-traceid"] == TRACE
    assert probe.json()["trace"] is None and "x-b3-traceid" not in probe.headers, "the probes trace nothing"


def test_a_span_ends_with_the_route_and_the_answer() -> None:
    current = start_request(TRACED, "req-1", "GET")
    end_request(current, 503, "/api/v2/compendium")
    assert current.span is not None and not current.span.is_recording(), "an ended span records no more"


def test_a_tracestate_goes_on_as_the_w3c_allows_it() -> None:
    """Spaces after a comma, vendor keys with *, values with ~, and repeated headers joined; it travels with the
    W3C trace, also beside B3 of the same trace."""
    found = _trace_headers(
        [(b"tracestate", b"rojo=00f067aa0ba902b7, congo=t61rcWkgMzE"), (b"tracestate", b"tenant*v=x~y")]
    )
    assert found["tracestate"] == "rojo=00f067aa0ba902b7, congo=t61rcWkgMzE,tenant*v=x~y"
    long_state = "vendor=" + "a" * 500
    assert _trace_headers([(b"tracestate", long_state.encode())])["tracestate"] == long_state
    assert _trace_headers([(b"tracestate", b"a=" + bytes([1]) + b"b")]) == {}
    parent = (b"traceparent", f"00-{TRACE}-00f067aa0ba902b7-01".encode())
    start_request([parent, (b"tracestate", b"rojo=00f067aa0ba902b7"), *TRACED[1:]], "req-1", "GET")
    assert outgoing_headers()["tracestate"] == "rojo=00f067aa0ba902b7"


def test_the_threads_of_a_request_carry_its_trace() -> None:
    """The LLM stages call the b-api from pool threads (app/concurrency.py): the trace goes with them."""
    start_request(TRACED, "req-1", "POST")

    seen = map_in_threads(lambda _: outgoing_headers(), [1, 2, 3], 3)

    assert all(headers["x-b3-traceid"] == TRACE for headers in seen)


# -- review of 2026-11-04 -------------------------------------------------------------------------------------------

W3C_TRACE = "0af7651916cd43dd8448eb211c80319c"


@pytest.mark.parametrize(
    "headers",
    [
        # a B3 trace id without a span id beside W3C of another trace
        [(b"x-b3-traceid", TRACE.encode()), (b"traceparent", f"00-{W3C_TRACE}-00f067aa0ba902b7-01".encode())],
        # B3 of a span beside W3C of another trace
        [*TRACED[1:3], (b"traceparent", f"00-{W3C_TRACE}-00f067aa0ba902b7-01".encode())],
        # the single header beside the multi header of another trace: the single one wins, as the propagator reads
        [(b"b3", f"{TRACE}-{CALLER_SPAN}-1".encode()), (b"x-b3-traceid", b"11111111111111111111111111111111")],
    ],
)
def test_b3_wins_and_log_answer_and_calls_name_one_trace(headers: list[tuple[bytes, bytes]]) -> None:
    start_request(headers, "req-1", "GET")
    sent = outgoing_headers()
    assert trace_id() == TRACE == sent["x-b3-traceid"]
    assert sent["traceparent"].split("-")[1] == TRACE


def test_a_b3_trace_of_zeros_is_no_trace() -> None:
    start_request([(b"x-b3-traceid", b"0000000000000000"), (b"x-b3-spanid", CALLER_SPAN.encode())], "req-1", "GET")
    assert trace_id() != "0000000000000000" and HEX32.fullmatch(trace_id() or "")
    assert outgoing_headers()["x-b3-traceid"] == trace_id()


def test_a_missing_sampling_decision_is_deferred_not_a_no() -> None:
    start_request(TRACED[1:3], "req-1", "GET")
    assert outgoing_headers()["x-b3-sampled"] == "1"


def test_a_span_ends_when_the_route_raises() -> None:
    ended: list[Any] = []

    async def boom(request: Request) -> JSONResponse:
        ended.append(_trace.get())
        raise RuntimeError("kaputt")

    app = RequestLog(Starlette(routes=[Route("/", boom)]), routes=[])
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/").status_code == 500
    assert ended[0].span is not None and not ended[0].span.is_recording()


def test_the_collector_gets_the_traces_path_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    seen: list[str] = []
    monkeypatch.setattr(trace_exporter.OTLPSpanExporter, "__init__", lambda self, endpoint: seen.append(endpoint))
    monkeypatch.setattr("opentelemetry.sdk.trace.export.BatchSpanProcessor.__init__", lambda self, exporter: None)
    monkeypatch.setattr("opentelemetry.sdk.trace.TracerProvider.add_span_processor", lambda self, processor: None)
    try:
        configure("x", "http://jaeger:4318/")
        configure("x", "http://jaeger:4318/v1/traces")
    finally:
        configure()
    assert seen == ["http://jaeger:4318/v1/traces", "http://jaeger:4318/v1/traces"]


def test_with_the_sdk_switched_off_no_trace_of_zeros_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    try:
        configure()
        start_request([], "req-1", "GET")
        assert trace_id() is None and span_id() is None
        start_request(TRACED, "req-1", "GET")
        assert trace_id() == TRACE
    finally:
        monkeypatch.delenv("OTEL_SDK_DISABLED")
        configure()
