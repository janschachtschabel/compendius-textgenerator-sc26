"""Threads of their own for the monitoring path: the probes, /metrics and the archive check before every request.

FastAPI runs plain endpoint functions in anyio's default pool (40 threads per worker), and synchronous compendium
requests hold those threads for up to REQUEST_TIMEOUT_S each. A probe that waits for a free thread misses its
deadline, and an orchestrator restarts a worker that is busy, not broken. The monitoring path still reads files and
SQLite off the event loop (a slow volume must not stall it), but in a small pool that requests cannot fill.
"""

from __future__ import annotations

from collections.abc import Callable

import anyio
import anyio.to_thread
from fastapi import Request

SYSTEM_THREADS = 4  # probes, scrapes and one stat call per request: all short


def system_limiter() -> anyio.CapacityLimiter:
    """The pool for ``app.state.system_limiter``; one per application."""
    return anyio.CapacityLimiter(SYSTEM_THREADS)


async def run_system[*Ts, T](request: Request, func: Callable[[*Ts], T], *args: *Ts) -> T:
    """Run ``func`` in the monitoring threads of the application that serves ``request``."""
    limiter: anyio.CapacityLimiter = request.app.state.system_limiter
    return await anyio.to_thread.run_sync(func, *args, limiter=limiter)
