"""Tracing in the platform's B3 format (D108, D115): one span per request, its ids in every log line and in the
headers of every call the request makes.

The platform traces in B3 and passes the trace id on from service to service, so the logs of all services can be
filtered for one request (Team 6, 2026-10-14). Its notes of 2026-11-03: the id comes along with a request and has to be
logged with it; the first service makes one where none comes; a framework writes the headers, one header per value
(X-B3-TraceId, X-B3-SpanId, X-B3-Sampled). So the service reads B3 (both forms) and W3C trace context with
OpenTelemetry, opens a span of its own as the child of the caller's, or a new trace without one, names trace and span in
its log lines and sends the trace on to the b-api and edu-sharing as B3 and W3C headers with its own span as the
parent. ``x-client-trace-id``, the trace id of a client, goes on unchanged and has a log field of its own. Spans go to
a collector (Jaeger, OTLP/HTTP) only where OTEL_EXPORTER_OTLP_ENDPOINT names one.

The values are caller input: a value with signs no trace id has, or longer than a log line should hold, is dropped,
not changed - a changed trace id joins nothing. The context variable reaches the threads of a request as its request
id does (app/concurrency.py).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagators.b3 import B3MultiFormat
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from opentelemetry.trace import SpanKind, Status, StatusCode, format_span_id, format_trace_id
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

log = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "compendious-text-generator"
REQUEST_ID = "X-Request-ID"  # the service's own id of the request, sent on as well
TRACE_RESPONSE = "X-B3-TraceId"  # the trace of a request in its answer, to name it when asking about it
CLIENT_TRACE = "x-client-trace-id"
B3_TRACE = "x-b3-traceid"
B3_SINGLE = "b3"
TRACE_STATE = "tracestate"
# B3 in its multi-header and single-header form, W3C trace context beside it, and the trace id of the client
TRACE_HEADERS = (
    CLIENT_TRACE,
    B3_TRACE,
    "x-b3-spanid",
    "x-b3-parentspanid",
    "x-b3-sampled",
    "x-b3-flags",
    B3_SINGLE,
    "traceparent",
    TRACE_STATE,
)
MAX_TRACE_CHARS = 256  # a B3 header holds some 70 signs, a client's trace id fewer
MAX_STATE_CHARS = 512  # W3C: vendors should pass on at least 512 signs of tracestate
_TRACE_VALUE = re.compile("[A-Za-z0-9._:@+/=,-]+")
# tracestate: any visible ASCII and spaces (after a comma, as proxies join headers), nothing that ends a line
_STATE_VALUE = re.compile("[ -~]+")
# A trace id of B3: 16 or 32 hex signs; "0", "1" and "d" alone are sampling decisions, no trace
_B3_ID = re.compile("[0-9a-f]{16}|[0-9a-f]{32}")
_SPAN_ID = re.compile("[0-9a-f]{16}")
# W3C first, B3 last: of two, B3 wins, the platform's format; start_request makes sure it does
W3C = TraceContextTextMapPropagator()
PROPAGATOR = CompositePropagator([W3C, B3MultiFormat()])


@dataclass
class RequestTrace:
    """The trace of one request: its span (none for the probes), what the caller sent, and the service's request id."""

    request_id: str
    method: str = ""
    span: trace.Span | None = None  # not recording where the caller's trace is not sampled; its ids hold all the same
    client_trace: str | None = None
    incoming_trace: str | None = None  # the B3 trace id as it came, 16 or 32 signs: logged as the platform logs it


@dataclass
class _Tracing:
    # the uvicorn master never builds the app and never calls configure: its lines name the service from the
    # environment as the workers' do (review of D115)
    service: str = os.environ.get("OTEL_SERVICE_NAME", "").strip() or DEFAULT_SERVICE_NAME
    provider: TracerProvider = field(default_factory=TracerProvider)


_tracing = _Tracing()
_trace: ContextVar[RequestTrace | None] = ContextVar("request_trace", default=None)


def configure(service: str = DEFAULT_SERVICE_NAME, otlp_endpoint: str = "") -> None:
    """The name the log lines and spans carry, and a collector for the spans where ``otlp_endpoint`` names one; once
    per process (each worker builds its app)."""
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service}))
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:  # the extra otlp is not installed: the ids are logged all the same
            log.warning("OTEL_EXPORTER_OTLP_ENDPOINT is set, but the exporter is not installed (extra otlp)")
        else:
            endpoint = otlp_endpoint.rstrip("/")
            if not endpoint.endswith("/v1/traces"):
                endpoint += "/v1/traces"
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    _tracing.provider.shutdown()
    _tracing.service, _tracing.provider = service, provider


def service_name() -> str:
    return _tracing.service


def start_request(
    headers: Iterable[tuple[bytes, bytes]], request_id: str, method: str, *, traced: bool = True
) -> RequestTrace:
    """The trace of a request coming in: the headers a trace id can have, and with ``traced`` a span of the service as
    the child of the caller's, or of a new trace where none came. It holds for the request (``trace_id``,
    ``outgoing_headers``); ``end_request`` closes it."""
    found = _trace_headers(headers)
    current = RequestTrace(request_id=request_id, method=method, client_trace=found.get(CLIENT_TRACE))
    if traced:
        tracer = _tracing.provider.get_tracer(__name__)
        current.span = tracer.start_span(method, context=_parent(found), kind=SpanKind.SERVER)
        incoming = _incoming_b3(found)
        if incoming is not None and current.span.get_span_context().trace_id == int(incoming, 16):
            current.incoming_trace = incoming  # logged and sent on as it came, 64 bits as 64 bits
    _trace.set(current)
    return current


def _parent(found: dict[str, str]) -> Context:
    """The caller's span: B3 where it names a trace (a missing sampling decision is deferred, so the service decides,
    as B3 has it), else W3C; the W3C tracestate goes with a B3 parent of the same trace."""
    carrier = dict(found)
    if B3_TRACE in carrier and "x-b3-sampled" not in carrier and "x-b3-flags" not in carrier:
        carrier["x-b3-sampled"] = "1"
    parent = PROPAGATOR.extract(carrier)
    chosen = trace.get_current_span(parent).get_span_context()
    incoming = _incoming_b3(found)
    if incoming is not None and (not chosen.is_valid or chosen.trace_id != int(incoming, 16)):
        # a B3 trace id without a span id, or beside another trace in the W3C headers: B3 wins all the same
        parent = _b3_parent(found, incoming)
        chosen = trace.get_current_span(parent).get_span_context()
    w3c = trace.get_current_span(W3C.extract(found)).get_span_context()
    if chosen.is_valid and w3c.is_valid and w3c.trace_id == chosen.trace_id and not chosen.trace_state:
        kept = trace.SpanContext(
            trace_id=chosen.trace_id,
            span_id=chosen.span_id,
            is_remote=True,
            trace_flags=chosen.trace_flags,
            trace_state=w3c.trace_state,
        )
        parent = trace.set_span_in_context(trace.NonRecordingSpan(kept))
    return parent


def end_request(current: RequestTrace, status: int, route: str | None) -> None:
    """Close the span of a request with its route and answer; a server error marks it as one."""
    span = current.span
    if span is None:
        return
    if route:
        span.update_name(f"{current.method} {route}")
        span.set_attribute("http.route", route)
    span.set_attribute("http.request.method", current.method)
    span.set_attribute("http.response.status_code", status)
    if status >= 500:
        span.set_status(Status(StatusCode.ERROR))
    span.end()


def trace_id() -> str | None:
    """The trace a log line names: the B3 trace id as the caller sent it, else the one of the service's span;
    ``None`` outside a traced request."""
    current = _trace.get()
    if current is None or current.span is None:
        return None
    context = current.span.get_span_context()  # invalid where OTEL_SDK_DISABLED switches the SDK off: no zeros
    return current.incoming_trace or (format_trace_id(context.trace_id) if context.is_valid else None)


def span_id() -> str | None:
    current = _trace.get()
    if current is None or current.span is None:
        return None
    context = current.span.get_span_context()
    return format_span_id(context.span_id) if context.is_valid else None


def client_trace_id() -> str | None:
    current = _trace.get()
    return current.client_trace if current is not None else None


def outgoing_headers() -> dict[str, str]:
    """The headers a call of the request being handled carries on: B3 (one header per value) and W3C with the
    service's span as the parent, the client's trace id and the request id; none outside a request."""
    current = _trace.get()
    if current is None:
        return {}
    headers: dict[str, str] = {}
    if current.client_trace:
        headers[CLIENT_TRACE] = current.client_trace
    if current.span is not None:
        PROPAGATOR.inject(headers, context=trace.set_span_in_context(current.span))
        if current.incoming_trace and len(current.incoming_trace) == 16:  # a 64-bit trace stays one (B3 allows both)
            headers[B3_TRACE] = current.incoming_trace
    headers[REQUEST_ID] = current.request_id
    return headers


def _trace_headers(headers: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    """The trace headers among the raw headers of a request, those a trace id can have; repeated tracestate headers
    are joined, as W3C has it."""
    found: dict[str, str] = {}
    for raw_name, raw_value in headers:
        name = raw_name.decode("latin-1").lower()
        if name not in TRACE_HEADERS or (name in found and name != TRACE_STATE):
            continue
        value = raw_value.decode("latin-1").strip()
        if name == TRACE_STATE:
            joined = f"{found[name]},{value}" if name in found else value
            if value and len(joined) <= MAX_STATE_CHARS and _STATE_VALUE.fullmatch(joined):
                found[name] = joined
        elif value and len(value) <= MAX_TRACE_CHARS and _TRACE_VALUE.fullmatch(value):
            found[name] = value
    return found


def _incoming_b3(found: dict[str, str]) -> str | None:
    """The B3 trace id, in the order the propagator reads the headers: the single header first; none of zeros."""
    single = found.get(B3_SINGLE, "").partition("-")[0]
    candidate = single if _B3_ID.fullmatch(single) else found.get(B3_TRACE, "")
    return candidate if _B3_ID.fullmatch(candidate) and int(candidate, 16) else None


def _b3_parent(found: dict[str, str], incoming: str) -> Context:
    """The B3 trace as the parent where the propagator did not take it: a trace id without a span id ("X-B3-TraceId"
    alone), or one beside another trace in the W3C headers. It is the trace the platform filters by, so the service's
    span joins it, under the caller's span id where one came and under one of its own making else."""
    single = found.get(B3_SINGLE, "").split("-")
    span = single[1] if len(single) > 1 else found.get("x-b3-spanid", "")
    sampled = (single[2] if len(single) > 2 else found.get("x-b3-sampled", "1")) not in ("0", "false")
    parent = trace.SpanContext(
        trace_id=int(incoming, 16),
        span_id=int(span, 16) if _SPAN_ID.fullmatch(span) and int(span, 16) else RandomIdGenerator().generate_span_id(),
        is_remote=True,
        trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED if sampled else trace.TraceFlags.DEFAULT),
    )
    return trace.set_span_in_context(trace.NonRecordingSpan(parent))
