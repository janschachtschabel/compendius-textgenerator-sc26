"""The path of a request as the router matches it, for the middlewares that look at it before the router runs."""

from __future__ import annotations

from starlette.types import Scope


def route_path(scope: Scope) -> str:
    """uvicorn puts a root path (UVICORN_ROOT_PATH) in front of ``path``, the router takes it off again, so
    /kompendium/health is /health (review of D110, audit 2026-10-15)."""
    path: str = scope["path"]
    root = scope.get("root_path", "")
    return (path[len(root) :] or "/") if root and path.startswith(root) else path
