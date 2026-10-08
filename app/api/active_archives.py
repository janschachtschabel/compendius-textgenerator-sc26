"""Follow the archives the ZIM sync makes active, without a restart."""

from __future__ import annotations

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.system_threads import run_system
from app.sources.zim.refresh import RegistryRefresher


class FollowActiveArchives:
    """ASGI middleware: one stat call per request; the archives are reopened only when the sync job replaced
    active.json. It runs in the monitoring threads, so a probe never waits for a thread that a compendium request
    holds. A plain ASGI middleware, so an error passes through it unchanged (app/api/request_log.py)."""

    def __init__(self, app: ASGIApp, refresher: RegistryRefresher) -> None:
        self.app = app
        self.refresher = refresher

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            await run_system(Request(scope), self.refresher.refresh)
        await self.app(scope, receive, send)
