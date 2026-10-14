"""The trace headers of a request, sent on with the calls it makes (D108).

The platform traces in the B3 format and passes ``x-client-trace-id`` on from service to service, so the logs of all
services can be filtered for one request (Team 6, 2026-10-14). The service reads these headers when a request comes
in, names the trace in its JSON log lines (``trace_id``: x-client-trace-id, else the B3 trace id) and sends them on
unchanged, together with its own ``X-Request-ID``, with its calls to the b-api and to edu-sharing. The context
variable reaches the threads of a request as its request id does (app/concurrency.py).

The values are caller input: a value with signs no trace id has, or longer than a log line should hold, is dropped,
not changed - a changed trace id joins nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextvars import ContextVar

REQUEST_ID = "X-Request-ID"  # the service's own id of the request, sent on as well
CLIENT_TRACE = "x-client-trace-id"
B3_TRACE = "x-b3-traceid"
B3_SINGLE = "b3"
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
    "tracestate",
)
MAX_TRACE_CHARS = 256  # tracestate holds up to 32 entries; a B3 header some 70 signs
_TRACE_VALUE = re.compile("^[A-Za-z0-9._:@+/=,-]+$")

_trace: ContextVar[dict[str, str]] = ContextVar("trace_headers", default={})  # noqa: B039  # never mutated


def take_trace_headers(headers: Iterable[tuple[bytes, bytes]], request_id: str) -> dict[str, str]:
    """The trace headers among the raw headers of a request, those a trace id can have, and ``request_id``, the id the
    service gave the request; they hold for the request."""
    found: dict[str, str] = {}
    for raw_name, raw_value in headers:
        name = raw_name.decode("latin-1").lower()
        if name not in TRACE_HEADERS or name in found:
            continue
        value = raw_value.decode("latin-1").strip()
        if value and len(value) <= MAX_TRACE_CHARS and _TRACE_VALUE.match(value):
            found[name] = value
    _trace.set({**found, REQUEST_ID: request_id})
    return found


def trace_id() -> str | None:
    """The trace a log line names: the client's trace id, else the B3 trace id; ``None`` outside a traced request."""
    found = _trace.get()
    single = found.get(B3_SINGLE, "").partition("-")[0]
    return found.get(CLIENT_TRACE) or found.get(B3_TRACE) or single or None


def outgoing_headers() -> dict[str, str]:
    """The headers a call of the request being handled carries on: its trace headers and its request id; none outside
    a request."""
    return dict(_trace.get())
