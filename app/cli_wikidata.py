"""``compendium wikidata …``: build the local Wikidata index, keep it in step, and report its state (D43, D64).

The index maps article titles of the German Wikipedia to Wikidata numbers. It is built from ``page_props`` and
``page`` of dumps.wikimedia.org/dewiki: ``build`` reads two dump files on disk and asks nothing online, ``sync``
downloads them itself when the index is missing or a newer Wikipedia archive needs a newer one - with ``--loop`` as
the ``wikidata-updater`` sidecar. A running service opens a new index by itself within a minute.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
import zlib
from datetime import timedelta
from pathlib import Path

import httpx

from app.jobs.lock import LockHeldError
from app.jobs.runner import parse_interval, run_periodically, stop_on_sigterm
from app.settings import get_settings
from app.sources.wikidata.index import IndexInUseError, WikidataIndex, build_index
from app.sources.wikidata.sync import WikidataSyncError, build_sync
from app.sources.zim.downloader import DownloadError

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
        print("  kein Wikidata-Index vorhanden (compendium wikidata build)")
    elif not index.available:
        print("  Wikidata-Index unbrauchbar (fremde Schemaversion oder beschädigte Datei); compendium wikidata build")
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
    try:
        meta = build_index(Path(args.page_props), Path(args.page), target)
    except IndexInUseError as exc:
        print(f"Wikidata-Index gebaut, aber nicht übernommen: {exc}", file=sys.stderr)
        return 1
    except (OSError, EOFError, zlib.error, ValueError, sqlite3.Error) as exc:  # EOFError: a dump cut short
        print(f"Wikidata-Index nicht gebaut: {exc}", file=sys.stderr)
        return 1
    print(
        f"Wikidata-Index {target}: {meta['articles']} Artikel, Dump vom {meta['dump'] or '?'}, "
        f"{time.monotonic() - started:.0f} s; der Dienst liest ihn nach einem Neustart"
    )
    return 0


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

    if args.loop:
        stop_on_sigterm()
        try:
            run_periodically(
                task,
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
