"""Every request once in the log, and an error nothing else handled once with its cause (logging review of 2026-10-08).

``RequestLog`` is the outermost middleware. It names the request (``X-Request-ID``: the caller's harmless signs or a
new id, app/logging.py), counts it for /metrics by its route template, and writes one line when it ends - method,
path with query, status, duration and client - also when the client has gone. An exception nothing else handled is
logged once, its type and message in the first line, and answered with a 500 that names the request id.

uvicorn's access line was the only trace of most requests: without duration, in the plain format without time or
request id, and missing when the client had gone; it writes none now (``--no-access-log``, app/serve.py). A probe that
answers - the healthcheck every 30 s, the scrape - writes no line: probes made 188 of 224 lines of a quiet dev
container. A plain ASGI middleware, unlike starlette's BaseHTTPMiddleware, which runs the app in a task group: an
error came out of three of them with an ExceptionGroup in front of the cause and every frame twice, and starlette
raised it on to uvicorn, which logged it a second time.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from urllib.parse import quote

from fastapi.routing import iter_route_contexts
from starlette.datastructures import MutableHeaders
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import JsonResponse
from app.api.metrics import METRICS_PATH
from app.logging import REQUEST_ID_HEADER, set_request_id
from app.observability.metrics import UNMATCHED_ROUTE, observe_request

log = logging.getLogger(__name__)

# An answer below 400 to these writes no line
PROBES = frozenset({"/health", "/ready", METRICS_PATH})
MAX_TARGET_CHARS = 500  # path and query in a line; h11 refuses a request line with headers over 16 KB
MAX_CAUSE_CHARS = 300
# A request of these methods reads; any other makes something and names its start: one that ends with its worker - the
# healthcheck window, the memory - left no line, as the line of a request comes when it ends
READS = frozenset({"GET", "HEAD", "OPTIONS"})
INTERNAL_ERROR = "Interner Fehler; bitte die Anfrage-ID melden"


def route_template(routes: Sequence[BaseRoute], scope: Scope) -> str:
    """The template of the route a request was meant for, when it left none in its scope - the metric's label.

    The 413 of BodySizeLimit answers a declared length before the router runs and counted as unmatched, beside the
    404s (audit 2026-09-29, S8); /docs, /redoc and /openapi.json are plain Starlette routes, which never store one. The
    templates are a fixed set, so the label values stay bounded; a path no route takes stays unmatched.
    """
    for context in iter_route_contexts(routes):  # the routes of the included routers as well (FastAPI 0.141)
        match, _ = context.matches(scope)
        if match is not Match.NONE:
            return context.path or UNMATCHED_ROUTE
    return UNMATCHED_ROUTE


class RequestLog:
    """ASGI middleware: request id, metric and one log line per request; a 500 for an error nothing else handled.

    ``routes`` is the application's live list of routes, so routes added after the middleware still name their
    requests."""

    def __init__(self, app: ASGIApp, routes: Sequence[BaseRoute]) -> None:
        self.app = app
        self.routes = routes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = set_request_id(_header(scope, REQUEST_ID_HEADER))
        started = time.perf_counter()
        if scope["method"] not in READS:
            target = _target(scope)
            log.info(
                "%s %s started", scope["method"], target, extra={"fields": {"method": scope["method"], "path": target}}
            )
        status = 500  # what the client sees when the app ends without an answer
        answered = False

        async def named(message: Message) -> None:
            nonlocal status, answered
            if message["type"] == "http.response.start":
                status, answered = message["status"], True
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, named)
        except Exception as exc:
            cause = " ".join(f"{type(exc).__name__}: {exc}".split())[:MAX_CAUSE_CHARS]
            log.exception("unhandled error in %s %s: %s", scope["method"], scope["path"], cause)
            if not answered:  # an answer begun cannot be taken back; the connection ends with it
                content = {"detail": INTERNAL_ERROR, "request_id": request_id}
                await JsonResponse(content, status_code=500)(scope, receive, named)
        finally:
            self._record(scope, status, time.perf_counter() - started)

    def _record(self, scope: Scope, status: int, seconds: float) -> None:
        path: str = scope["path"]
        route = getattr(scope.get("route"), "path", None) or route_template(self.routes, scope)
        if path != METRICS_PATH:  # a scrape is no request of the service
            observe_request(scope["method"], route, status, seconds)
        if path in PROBES and status < 400:
            return
        target = _target(scope)
        client = scope.get("client")
        fields = {
            "method": scope["method"],
            "path": target,
            "route": route,
            "status": status,
            "duration_ms": round(seconds * 1000),
            "client": client[0] if client else "-",
        }
        log.info("%s %s %d %d ms", fields["method"], target, status, fields["duration_ms"], extra={"fields": fields})


def _target(scope: Scope) -> str:
    """Path and query of the request as a line can hold them: quoted, every other sign escaped, cut."""
    query = scope.get("query_string", b"").decode("latin-1")
    return _printable(quote(scope["path"]) + (f"?{query}" if query else ""))[:MAX_TARGET_CHARS]


def _header(scope: Scope, name: str) -> str | None:
    wanted = name.lower().encode("latin-1")
    for key, value in scope["headers"]:
        if key == wanted:
            return str(value.decode("latin-1"))
    return None


def _printable(text: str) -> str:
    """``text`` with every sign a terminal or a line format would act on escaped, as in a Python literal."""
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)
