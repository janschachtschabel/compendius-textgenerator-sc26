"""The internal port (D110): probes, metrics and status answer on INTERNAL_PORT only.

Team 6 (2026-10-14) wants the public API on one port, released by the ingress, and /health, /ready and /metrics on a
second one that stays inside the cluster; Jan (2026-10-15) put the status endpoints there as well. The workers listen on
both ports (app/serve.py); this middleware answers an internal path on the public port with a 404, as if it did not
exist, and leaves everything else alone. On the internal port the cluster may ask every path. The admin paths stay on
the public port behind ADMIN_TOKEN.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.errors import JsonResponse
from app.api.metrics import METRICS_PATH

INTERNAL_PATHS = frozenset({"/health", "/ready", METRICS_PATH, "/api/v2/zim/status", "/api/v2/lehrplan/status"})


class InternalOnly:
    """ASGI middleware: a 404 for an internal path asked on any port but ``port``."""

    def __init__(self, app: ASGIApp, port: int) -> None:
        self.app = app
        self.port = port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _route_path(scope) in INTERNAL_PATHS and _server_port(scope) != self.port:
            await JsonResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _route_path(scope: Scope) -> str:
    """The path the router matches: uvicorn puts a root path (UVICORN_ROOT_PATH) in front of ``path``, the router
    takes it off again, so /kompendium/health is /health (review of D110)."""
    path: str = scope["path"]
    root = scope.get("root_path", "")
    return (path[len(root) :] or "/") if root and path.startswith(root) else path


def _server_port(scope: Scope) -> int | None:
    """The port the connection came in on: the server's socket, not what a proxy or the Host header says."""
    server = scope.get("server")
    return server[1] if server else None
