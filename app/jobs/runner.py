"""Periodic job loop shared by the ZIM sync and later harvests: interval, trigger file, stop event."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

log = logging.getLogger(__name__)

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(text: str) -> timedelta:
    """Parse ``30d``, ``12h``, ``45m`` or ``90s`` (case-insensitive); anything else raises ``ValueError``."""
    match = _INTERVAL_RE.match(text or "")
    if not match:
        raise ValueError(f"invalid interval {text!r}; use <number><s|m|h|d>, e.g. 30d")
    return timedelta(seconds=int(match.group(1)) * _UNITS[match.group(2).lower()])


def run_periodically(
    task: Callable[[], None],
    interval: timedelta,
    *,
    retry_after: timedelta | None = None,
    poll_s: float = 60.0,
    trigger_file: Path | None = None,
    stop: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run ``task`` now and then every ``interval``; a trigger file runs it early and is removed.

    The loop wakes every ``poll_s`` seconds to look for the trigger file and the stop event.
    Exceptions from the task are logged and the loop continues, after ``retry_after`` when that is shorter
    than the interval; it returns once ``stop`` is set.
    """
    stop = stop or threading.Event()
    next_run = clock()
    while not stop.is_set():
        triggered = trigger_file is not None and trigger_file.exists()
        if triggered or clock() >= next_run:
            if triggered and trigger_file is not None:
                trigger_file.unlink(missing_ok=True)
                log.info("run requested via %s", trigger_file.name)
            wait = interval
            try:
                task()
            except Exception:
                wait = min(interval, retry_after) if retry_after is not None else interval
                log.exception("job failed; next attempt in %s", wait)
            next_run = clock() + wait.total_seconds()
        if stop.is_set():
            break
        sleep(min(poll_s, max(next_run - clock(), 0.0)))
