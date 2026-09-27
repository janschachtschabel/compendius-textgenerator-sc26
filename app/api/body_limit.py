"""The size of a request body, bounded before anything reads it (audit 2026-09-27, SE-02).

FastAPI reads a whole body and parses it before any dependency runs, the rate limit included, and uvicorn bounds
nothing. A single anonymous request of a few hundred MB cost about three times that in memory and blocked the event
loop of its worker, health checks included. ``BodySizeLimit`` answers 413 to a declared length over the limit
without reading a byte, and counts a body that declares none (chunked) while it arrives.
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import JsonResponse
from app.domain.requests import EXISTING_MARKDOWN_MAX_CHARS

# The largest field, existing_markdown, with every character spelled as a six-byte JSON escape, and a megabyte for
# all other fields together (the next largest, the text of /qa and /entities, takes 50,000 characters)
MAX_BODY_BYTES = 6 * EXISTING_MARKDOWN_MAX_CHARS + 1_000_000
# A refused body stays unread in the connection; closing it keeps those bytes from being taken for the next request
CLOSE = {"Connection": "close"}


def too_large(max_bytes: int) -> str:
    return f"Der Anfragekörper ist zu groß: höchstens {max_bytes} Byte."


class BodySizeLimit:
    """ASGI middleware: 413 for a request body over ``max_bytes``."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            response = JsonResponse({"detail": too_large(self.max_bytes)}, status_code=413, headers=CLOSE)
            await response(scope, receive, send)
            return
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI hands an HTTPException raised while it reads the body on to the exception handler
                    raise HTTPException(status_code=413, detail=too_large(self.max_bytes), headers=CLOSE)
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
