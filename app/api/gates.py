"""Rate limit, key and admin token are asked before the body is read (audit 2026-09-28, SE-18).

FastAPI reads and parses a request body before any dependency runs, so every body up to its limit was parsed
before ``rate_limited``, ``require_api_key`` or ``require_admin`` could refuse it: 13 MB made 312 MB of Python objects,
and the 401 without a key came after half a second instead of 49 ms. A router built with ``route_class=GatedRoute``
asks the gates a route declares first, in the order the route names them. The dependencies stay declared, so /docs
still shows the key and the token, and each gate decides once per request: FastAPI's own call later passes at once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

Gate = Callable[[Request], Awaitable[None]]

# The dependencies that can decide on the request line and headers alone, each with how to ask it without FastAPI;
# the modules of the gates enter themselves here
EARLY: dict[Callable[..., Any], Gate] = {}
_ASKED = "compendium.gates_asked"  # the scope key under which a request keeps the gates it has passed


def first_time(request: Request, gate: str) -> bool:
    """True the first time ``gate`` asks about this request; a gate that already let it pass returns at once."""
    asked: set[str] = request.scope.setdefault(_ASKED, set())
    if gate in asked:
        return False
    asked.add(gate)
    return True


class GatedRoute(APIRoute):
    """A route whose gates are asked before FastAPI reads its body."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        gates = [EARLY[dependency.call] for dependency in self.dependant.dependencies if dependency.call in EARLY]
        if not gates:
            return handler

        async def gated(request: Request) -> Response:
            for gate in gates:
                await gate(request)
            return await handler(request)

        return gated
