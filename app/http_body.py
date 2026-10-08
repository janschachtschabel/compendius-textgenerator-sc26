"""Reading the answer of an upstream service within a bound (audit 2026-10-03, F12).

The clients of edu-sharing and the b-api read every answer whole before parsing it; an answer of a faulty or
compromised upstream - an allowlisted repository or the gateway - could fill the memory of a worker that way. The body
is read as a stream and counted after decoding, so a compressed answer counts by what it unpacks to.
"""

from __future__ import annotations

import httpx


class AnswerTooLargeError(ValueError):
    """The answer runs past the bound; reading stopped there."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"mehr als {limit:,} Byte".replace(",", "."))
        self.limit = limit


def read_bounded(response: httpx.Response, limit: int) -> bytes:
    """The decoded body of a streamed ``response``; ``AnswerTooLargeError`` once it runs past ``limit`` bytes."""
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise AnswerTooLargeError(limit)
    return bytes(body)
