"""Requests per client and minute on the expensive endpoints: ``RATE_LIMIT`` as in the old service.

The counter lives in each worker process, so with several uvicorn workers a client can get up to
workers x limit requests through. Behind a reverse proxy, uvicorn only sees the client address when
``FORWARDED_ALLOW_IPS`` names the proxy; otherwise all clients share the proxy's window. A gateway
limit is the stronger control; this one keeps a single client from monopolising the service.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request

MAX_CLIENTS = 10_000  # windows kept before idle clients are forgotten


class RateLimiter:
    """Sliding window per client: at most ``limit`` requests within ``window_s`` seconds."""

    def __init__(self, limit: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def retry_after(self, client: str) -> int | None:
        """Count a request of ``client``; ``None`` when it may pass, otherwise the seconds until a slot frees."""
        now = self._clock()
        hits = self._hits.setdefault(client, deque())
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, math.ceil(hits[0] + self.window_s - now))  # the slot frees exactly then
        hits.append(now)
        if len(self._hits) > MAX_CLIENTS:
            self._forget_idle(now)
        return None

    def _forget_idle(self, now: float) -> None:
        idle = [client for client, hits in self._hits.items() if not hits or hits[-1] <= now - self.window_s]
        for client in idle:
            del self._hits[client]


async def rate_limited(request: Request) -> None:
    """Route dependency; ``async`` so it runs on the event loop and needs no lock around the counters."""
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    client = request.client.host if request.client else "unbekannt"
    retry = limiter.retry_after(client)
    if retry is not None:
        raise HTTPException(
            status_code=429,
            detail="Zu viele Anfragen; bitte später erneut versuchen.",
            headers={"Retry-After": str(retry)},
        )
