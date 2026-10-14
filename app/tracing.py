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
MAX_TRACE_CHARS = 256  # a B3 header holds some 70 signs, a client's trace id fewer
MAX_STATE_CHARS = 512  # W3C: vendors should pass on at least 512 signs of tracestate
TRACE_STATE = "tracestate"
_TRACE_VALUE = re.compile("[A-Za-z0-9._:@+/=,-]+")
# tracestate: any visible ASCII and spaces (after a comma, as proxies join headers), nothing that ends a line
_STATE_VALUE = re.compile("[ -~]+")
# A trace id of B3: 16 or 32 hex signs; "0", "1" and "d" alone are sampling decisions, no trace
_B3_ID = re.compile("[0-9a-f]{16}|[0-9a-f]{32}")

_trace: ContextVar[dict[str, str]] = ContextVar("trace_headers", default={})  # noqa: B039  # never mutated


def take_trace_headers(headers: Iterable[tuple[bytes, bytes]], request_id: str) -> dict[str, str]:
    """The trace headers among the raw headers of a request, those a trace id can have, and ``request_id``, the id the
    service gave the request; they hold for the request. Repeated tracestate headers are joined, as W3C has it."""
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
    _trace.set({**found, REQUEST_ID: request_id})
    return found


def trace_id() -> str | None:
    """The trace a log line names: the client's trace id, else the B3 trace id, else that of W3C traceparent; ``None``
    outside a traced request."""
    found = _trace.get()
    if found.get(CLIENT_TRACE):
        return found[CLIENT_TRACE]
    candidates = (
        found.get(B3_TRACE, ""),
        found.get(B3_SINGLE, "").partition("-")[0],
        found.get("traceparent", "-").split("-")[1] if found.get("traceparent", "").count("-") >= 3 else "",
    )
    return next((candidate for candidate in candidates if _B3_ID.fullmatch(candidate)), None)


def outgoing_headers() -> dict[str, str]:
    """The headers a call of the request being handled carries on: its trace headers and its request id; none outside
    a request."""
    return dict(_trace.get())
