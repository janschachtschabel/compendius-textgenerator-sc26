"""Periodic job loop shared by the ZIM sync and later harvests: interval, trigger file, stop event."""

from __future__ import annotations

import logging
import re
import signal
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import __version__, revision
from app.files import atomic_write_text

log = logging.getLogger(__name__)

# A waiting loop signs life at least this often. The ZIM loop checks every 30 days (D16) and the curriculum loop
# every seven, and a check without a pull wrote nothing: a stopped sidecar showed only after weeks, and on
# 2026-09-27 the sidecars were missing on the server unnoticed (audit 2026-09-28, BE-15).
ALIVE_EVERY = timedelta(hours=1)
# The shortest interval a setting may name: an interval of 0 ran a loop without a pause, 1000 runs in 0.0 s, and the
# GND sidecar asked data.dnb.de three times a run (audit 2026-09-29, Q4). No setting or test used less than 90 s.
MIN_INTERVAL = timedelta(minutes=1)

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(text: str) -> timedelta:
    """Parse ``30d``, ``12h``, ``45m`` or ``90s`` (case-insensitive), at least ``MIN_INTERVAL``; anything else raises
    ``ValueError``."""
    match = _INTERVAL_RE.match(text or "")
    if not match:
        raise ValueError(f"invalid interval {text!r}; use <number><s|m|h|d>, e.g. 30d")
    interval = timedelta(seconds=int(match.group(1)) * _UNITS[match.group(2).lower()])
    if interval < MIN_INTERVAL:
        raise ValueError(f"interval {text!r} is too short; use at least 1m (60s), e.g. 30d")
    return interval


def mark_alive(path: Path) -> None:
    """Write the time into ``path``: the sign of life of a job loop, which the API reports as a metric."""
    atomic_write_text(path, datetime.now(UTC).isoformat())


def last_alive(path: Path) -> datetime | None:
    """The last sign of life written into ``path``; ``None`` before the first one or for a file that is no time."""
    try:
        return datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def stop_on_sigterm() -> None:
    """Let SIGTERM raise KeyboardInterrupt, as Ctrl+C does.

    A container stop sends SIGTERM to PID 1 and kills it ten seconds later. Python installs no SIGTERM handler,
    and the kernel drops a signal without a handler for PID 1 (elsewhere it ends the process at once), so without
    this a running job never wrote its final status or released its lock, and the next container waited for the
    lock to go stale.
    """
    signal.signal(signal.SIGTERM, signal.default_int_handler)


def run_periodically(
    task: Callable[[], bool | timedelta | None],
    interval: timedelta,
    *,
    retry_after: timedelta | None = None,
    poll_s: float = 60.0,
    trigger_file: Path | None = None,
    stop: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    alive: Callable[[], None] | None = None,
    name: str = "job",
    expected: tuple[type[Exception], ...] = (),
) -> None:
    """Run ``task`` now and then every ``interval``; a trigger file runs it early and is removed.

    The loop wakes every ``poll_s`` seconds to look for the trigger file and the stop event.
    A task that raises (logged) or returns ``False`` runs again after ``retry_after`` when that is shorter than
    the interval; one that returns a ``timedelta`` runs again after it when that is shorter - the ZIM sync, when a
    retired archive may go (audit 2026-09-28, BE-12). ``alive`` is called when the loop starts and at least every
    ``ALIVE_EVERY`` while it waits; one that fails is logged and tried again an hour later. The loop returns once
    ``stop`` is set.

    A failure names the job (``name``). One of the ``expected`` kinds - a source not reachable, a lock another run
    holds - is one WARNING with its cause; any other is logged with its traceback. Every failure was "job failed" with
    a traceback: 24 ERROR tracebacks a day of an outage at MEM or the DNB (logging review of 2026-10-08).
    """
    stop = stop or threading.Event()
    # The updaters have no /health: the version and the commit tell an updater left on an old image (logging review)
    log.info(
        "%s: loop started, Kompendium %s (revision %s), every %s", name, __version__, revision() or "local", interval
    )
    next_run = next_alive = clock()
    while not stop.is_set():
        if alive is not None and clock() >= next_alive:
            try:
                alive()
            except OSError as exc:  # a full or read-only volume: the job itself may still run
                log.warning("cannot write the sign of life: %s", exc)
            next_alive = clock() + ALIVE_EVERY.total_seconds()
        triggered = trigger_file is not None and trigger_file.exists()
        if triggered or clock() >= next_run:
            if triggered and trigger_file is not None:
                trigger_file.unlink(missing_ok=True)
                log.info("run requested via %s", trigger_file.name)
            early = min(interval, retry_after) if retry_after is not None else interval
            try:
                result = task()
                if result is False:
                    wait = early
                elif isinstance(result, timedelta):
                    wait = min(interval, max(result, timedelta(0)))
                else:
                    wait = interval
            except expected as exc:
                wait = early
                log.warning("%s did not run: %s: %s; next attempt in %s", name, type(exc).__name__, exc, wait)
            except Exception:
                wait = early
                log.exception("%s failed; next attempt in %s", name, wait)
            next_run = clock() + wait.total_seconds()
        if stop.is_set():
            break
        wake = min(next_run, next_alive) if alive is not None else next_run
        sleep(min(poll_s, max(wake - clock(), 0.0)))
