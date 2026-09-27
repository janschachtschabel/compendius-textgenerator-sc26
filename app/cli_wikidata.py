"""``compendium wikidata …``: build the local Wikidata index, keep it in step, and report its state (D43, D64).

The index maps article titles of the German Wikipedia to Wikidata numbers. It is built from ``page_props`` and
``page`` of dumps.wikimedia.org/dewiki: ``build`` reads two dump files on disk and asks nothing online, ``sync``
downloads them itself when the index is missing or a newer Wikipedia archive needs a newer one - with ``--loop`` as
the ``wikidata-updater`` sidecar. A running service opens a new index by itself within a minute.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
import zlib
from datetime import timedelta
from pathlib import Path

import httpx

from app.jobs.lock import LockHeldError, acquire_lock
from app.jobs.runner import parse_interval, run_periodically, stop_on_sigterm
from app.settings import get_settings
from app.sources.wikidata.index import IndexInUseError, WikidataIndex, build_index
from app.sources.wikidata.sync import LOCK_FILE, LOCK_STALE_S, WikidataSyncError, build_sync
from app.sources.zim.downloader import DownloadError, TransferError

POLL_SECONDS = 60
RETRY_AFTER_FAILURE = timedelta(hours=1)
REASONS = {
    "no index": "kein Index vorhanden",
    "index unusable": "Index unbrauchbar",
    "archive newer than the index": "Wikipedia-Archiv neuer als der Dump des Index",
    "forced": "erzwungen",
}


def cmd_status(args: argparse.Namespace) -> int:
    index = WikidataIndex(get_settings().wikidata_db_path)
    print(f"Wikidata-Index: {index.path}")
    if not index.exists:
        print("  kein Wikidata-Index vorhanden (compendium wikidata sync, ohne Netz: build)")
    elif not index.available:
        print("  Wikidata-Index unbrauchbar (fremdes Schema, beschädigte Datei); compendium wikidata sync --force")
    else:
        meta = index.meta()
        print(
            f"  {meta['articles']} Artikel | Dump vom {meta['dump'] or '?'} | gebaut {meta['built_at']} "
            f"| aus {', '.join(meta['sources'])}"
        )
    index.close()
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    target = get_settings().wikidata_db_path
    started = time.monotonic()
    try:  # the sync's lock: two builds would write the same .part file, and one could swap in the other's half
        lock = acquire_lock(
            target.parent / LOCK_FILE, stale_s=LOCK_STALE_S, now=time.time, owner=f"pid {os.getpid()} wikidata build"
        )
    except LockHeldError as exc:
        print(f"Wikidata-Index nicht gebaut: ein anderer Bau läuft ({exc})", file=sys.stderr)
        return 1
    try:
        meta = build_index(Path(args.page_props), Path(args.page), target)
    except IndexInUseError as exc:
        print(f"Wikidata-Index gebaut, aber nicht übernommen: {exc}", file=sys.stderr)
        return 1
    except (OSError, EOFError, zlib.error, ValueError, sqlite3.Error) as exc:  # EOFError: a dump cut short
        print(f"Wikidata-Index nicht gebaut: {exc}", file=sys.stderr)
        return 1
    finally:
        lock.release()
    print(
        f"Wikidata-Index {target}: {meta['articles']} Artikel, Dump vom {meta['dump'] or '?'}, "
        f"{time.monotonic() - started:.0f} s; der Dienst übernimmt ihn binnen einer Minute"
    )
    return 0


def _repeats(exc: BaseException) -> bool:
    """A failure the same run would repeat: a checksum or size that does not match, a dump the build cannot read, an
    index a running service holds open (Windows). The loop then waits for its next check, not RETRY_AFTER_FAILURE:
    an hourly retry would fetch the same 420 MB again and again."""
    if isinstance(exc, TransferError):  # cut short on the way: the next run resumes the .part
        return False
    return isinstance(exc, (DownloadError, IndexInUseError, EOFError, zlib.error, ValueError, sqlite3.Error))


def cmd_sync(args: argparse.Namespace) -> int:
    settings = get_settings()
    sync = build_sync(settings)
    force = bool(args.force)

    def task() -> None:
        nonlocal force
        reason = sync.due(force=force)
        force = False
        if reason is None:
            print("Wikidata-Index ist aktuell: vorhanden, und kein neueres Wikipedia-Archiv braucht einen neueren Dump")
            return
        print(f"Wikidata-Index wird gebaut ({REASONS.get(reason, reason)}): zwei Dumps laden, rund 420 MB")
        meta = sync.run(reason)
        print(f"Wikidata-Index {sync.index_path}: {meta['articles']} Artikel, Dump vom {meta['dump'] or '?'}")

    def checked() -> None:
        try:
            task()
        except Exception as exc:
            if not _repeats(exc):
                raise  # the loop logs it and tries again after RETRY_AFTER_FAILURE
            print(f"Wikidata-Index nicht gebaut, der alte bleibt bis zur nächsten Prüfung: {exc}", file=sys.stderr)

    if args.loop:
        stop_on_sigterm()
        try:
            run_periodically(
                checked,
                parse_interval(settings.wikidata_check_interval),
                retry_after=RETRY_AFTER_FAILURE,
                poll_s=POLL_SECONDS,
            )
        except KeyboardInterrupt:  # Ctrl+C or a container stop; a run has written its status
            print("Wikidata-Schleife beendet.")
        return 0
    try:
        task()
    except (
        WikidataSyncError, DownloadError, LockHeldError, httpx.HTTPError,  # the dump site or another run
        OSError, EOFError, zlib.error, ValueError, sqlite3.Error,  # the build, as cmd_build names them
    ) as exc:  # fmt: skip
        print(f"Wikidata-Index nicht gebaut, der vorhandene bleibt: {exc}", file=sys.stderr)
        return 1
    return 0


def add_wikidata_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("wikidata", help="Wikidata-Index aus Dumps der deutschen Wikipedia: build, sync, status")
    commands = parser.add_subparsers(dest="wikidata_command", required=True)

    status = commands.add_parser("status", help="Stand des Index: Artikel, Datum des Dumps, Quelldateien")
    status.set_defaults(func=cmd_status)

    build = commands.add_parser("build", help="Index aus page_props und page bauen (lokale Dateien, kein Netz)")
    build.add_argument("--page-props", required=True, help="dewiki-…-page_props.sql.gz")
    build.add_argument("--page", required=True, help="dewiki-…-page.sql.gz")
    build.set_defaults(func=cmd_build)

    sync = commands.add_parser(
        "sync", help="Index bauen, wenn er fehlt oder ein neueres Wikipedia-Archiv einen neueren Dump braucht"
    )
    sync.add_argument("--loop", action="store_true", help="Sidecar: prüfen nach WIKIDATA_CHECK_INTERVAL (1d)")
    sync.add_argument("--force", action="store_true", help="auch einen aktuellen Index neu bauen")
    sync.set_defaults(func=cmd_sync)
