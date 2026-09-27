"""Requests per client and minute on the expensive endpoints: ``RATE_LIMIT`` as in the old service.

The counter lives in each worker process, so with several uvicorn workers a client can get up to
workers x limit requests through. Behind a reverse proxy, uvicorn only sees the client address when
``FORWARDED_ALLOW_IPS`` names the proxy; otherwise all clients share the proxy's window. A gateway
limit is the stronger control; this one keeps a single client from monopolising the service.
"""

from __future__ import annotations

import ipaddress
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

# Windows kept at most. Beyond it the least recently seen client is forgotten, at constant cost per request: a scan
# over all windows on every request dropped only idle ones, cost 6.8 ms with 30,000 active clients and bounded
# nothing (audit 2026-09-27, SE-07). A forgotten client starts afresh.
MAX_CLIENTS = 10_000


def client_key(host: str) -> str:
    """The window a client counts in: its address, an IPv6 address by its /64 - a connection often holds a whole
    /64, and address by address one client would get a window per address (SE-07)."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host  # no address, e.g. the test client's name
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


class RateLimiter:
    """Sliding window per client: at most ``limit`` requests within ``window_s`` seconds."""

    def __init__(self, limit: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()  # least recently seen first

    def __len__(self) -> int:
        return len(self._hits)

    def retry_after(self, client: str) -> int | None:
        """Count a request of ``client``; ``None`` when it may pass, otherwise the seconds until a slot frees."""
        now = self._clock()
        hits = self._hits.get(client)
        if hits is None:
            hits = self._hits[client] = deque()
        else:
            self._hits.move_to_end(client)
        while hits and hits[0] <= now - self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, math.ceil(hits[0] + self.window_s - now))  # the slot frees exactly then
        hits.append(now)
        while len(self._hits) > MAX_CLIENTS:
            self._hits.popitem(last=False)
        return None


async def rate_limited(request: Request) -> None:
    """Route dependency; ``async`` so it runs on the event loop and needs no lock around the counters."""
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    client = client_key(request.client.host) if request.client else "unbekannt"
    retry = limiter.retry_after(client)
    if retry is not None:
        raise HTTPException(
            status_code=429,
            detail="Zu viele Anfragen; bitte später erneut versuchen.",
            headers={"Retry-After": str(retry)},
        )
