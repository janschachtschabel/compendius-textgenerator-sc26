"""What the index commands share (``compendium wikidata …``, ``compendium gnd …``; D64, D65): a sync that runs once or
loops as the sidecar, and a build by hand from files on disk that takes the sync's lock.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import zlib
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

import httpx

from app.jobs.runner import mark_alive, parse_interval, run_periodically, stop_on_sigterm
from app.locks import LockHeldError, acquire_lock
from app.sources.dump_sync import LOCK_STALE_S, ReleaseNotFoundError
from app.sources.local_index import IndexInUseError
from app.sources.zim.downloader import DownloadError, TransferError

POLL_SECONDS = 60
RETRY_AFTER_FAILURE = timedelta(hours=1)
# The source or another run, then the build (EOFError: a dump cut short)
SYNC_ERRORS = (ReleaseNotFoundError, DownloadError, LockHeldError, httpx.HTTPError, OSError, EOFError, zlib.error,
               ValueError, sqlite3.Error)  # fmt: skip
BUILD_ERRORS = (OSError, EOFError, zlib.error, ValueError, sqlite3.Error)


def fails_again(exc: BaseException) -> bool:
    """A failure the same run would repeat: a checksum or size that does not match, a dump the build cannot read, an
    index a running service holds open (Windows). The loop then waits for its next check, not RETRY_AFTER_FAILURE:
    an hourly retry would fetch the same hundreds of MB again and again."""
    if isinstance(exc, TransferError):  # cut short on the way: the next run resumes the .part
        return False
    return isinstance(exc, (DownloadError, IndexInUseError, EOFError, zlib.error, ValueError, sqlite3.Error))


def run_sync(task: Callable[[], None], *, loop: bool, interval: str, name: str, alive: Path) -> int:
    """Run ``task`` - check, and build when due - once (exit 1 on a failure) or as the sidecar's loop.

    ``name`` ("Wikidata-Index") heads the messages; in the loop a failure the same run would repeat waits for the
    next check, any other is logged by the loop and tried again after RETRY_AFTER_FAILURE. The loop writes its sign of
    life into ``alive``, as the ZIM and curriculum loops do: without one, a sidecar that never ran had no series any
    alert could fire on (audit 2026-09-29, Q5)."""

    def checked() -> None:
        try:
            task()
        except Exception as exc:
            if not fails_again(exc):
                raise
            print(f"{name} nicht gebaut, der alte bleibt bis zur nächsten Prüfung: {exc}", file=sys.stderr)

    if loop:
        stop_on_sigterm()
        try:
            run_periodically(
                checked,
                parse_interval(interval),
                retry_after=RETRY_AFTER_FAILURE,
                poll_s=POLL_SECONDS,
                alive=partial(mark_alive, alive),
            )
        except KeyboardInterrupt:  # Ctrl+C or a container stop; a run has written its status
            print(f"{name}: Schleife beendet.")
        return 0
    try:
        task()
    except SYNC_ERRORS as exc:
        print(f"{name} nicht gebaut, der vorhandene bleibt: {exc}", file=sys.stderr)
        return 1
    return 0


def run_build(
    target: Path, *, lock_file: str, name: str, build: Callable[[], dict[str, Any]], describe: Callable[[Any], str]
) -> int:
    """Build ``target`` from files on disk under the sync's lock: two builds would write the same ``.part`` file, and
    one could swap in the other's half."""
    started = time.monotonic()
    try:
        lock = acquire_lock(
            target.parent / lock_file, stale_s=LOCK_STALE_S, now=time.time, owner=f"pid {os.getpid()} build"
        )
    except LockHeldError as exc:
        print(f"{name} nicht gebaut: ein anderer Bau läuft ({exc})", file=sys.stderr)
        return 1
    try:
        meta = build()
    except IndexInUseError as exc:
        print(f"{name} gebaut, aber nicht übernommen: {exc}", file=sys.stderr)
        return 1
    except BUILD_ERRORS as exc:
        print(f"{name} nicht gebaut: {exc}", file=sys.stderr)
        return 1
    finally:
        lock.release()
    print(
        f"{name} {target}: {describe(meta)}, {time.monotonic() - started:.0f} s; "
        "der Dienst übernimmt ihn binnen einer Minute"
    )
    return 0
