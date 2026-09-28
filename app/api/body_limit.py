"""The size of a request body, bounded before anything reads it (audit 2026-09-27, SE-02).

FastAPI reads a whole body and parses it before any dependency runs, the rate limit included, and uvicorn bounds
nothing. A single anonymous request of a few hundred MB cost about three times that in memory and blocked the event
loop of its worker, health checks included. ``BodySizeLimit`` answers 413 to a declared length over the limit
without reading a byte, and counts a body that declares none (chunked) while it arrives.

Each route has its bound (audit 2026-09-28, SE-18): only an earlier compendium (``existing_markdown``) and a whole
template need 13 MB; every other body stays under ``REQUEST_BODY_MAX_BYTES``, by default a megabyte. The one bound
for all let 13 MB reach ``json.loads`` on /qa, whose largest field takes 50,000 characters.
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import JsonResponse
from app.domain.requests import EXISTING_MARKDOWN_MAX_CHARS

# The largest field, existing_markdown, with every character spelled as a six-byte JSON escape, and a megabyte for
# all other fields together (the next largest, the text of /qa and /entities, takes 50,000 characters)
LARGE_BODY_BYTES = 6 * EXISTING_MARKDOWN_MAX_CHARS + 1_000_000
# A refused body stays unread in the connection; closing it keeps those bytes from being taken for the next request
CLOSE = {"Connection": "close"}


def too_large(max_bytes: int) -> str:
    return f"Der Anfragekörper ist zu groß: höchstens {max_bytes} Byte."


def takes_large_body(method: str, path: str) -> bool:
    """The two requests whose body may be large: a compendium with an earlier one, and a whole template."""
    return (method == "POST" and path == "/api/v2/compendium") or (
        method == "PUT" and path.startswith("/api/v2/templates/")
    )


class BodySizeLimit:
    """ASGI middleware: 413 for a request body over the bound of its route, ``max_bytes`` or ``LARGE_BODY_BYTES``."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        bound = self.max_bytes
        if takes_large_body(scope["method"], scope["path"]):
            bound = max(bound, LARGE_BODY_BYTES)
        declared = _declared_length(scope)
        if declared is not None and declared > bound:
            response = JsonResponse({"detail": too_large(bound)}, status_code=413, headers=CLOSE)
            await response(scope, receive, send)
            return
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > bound:
                    # FastAPI hands an HTTPException raised while it reads the body on to the exception handler
                    raise HTTPException(status_code=413, detail=too_large(bound), headers=CLOSE)
            return message

        await self.app(scope, counted, send)


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None  # uvicorn refuses a malformed length itself; the count below still bounds the body
    return None
