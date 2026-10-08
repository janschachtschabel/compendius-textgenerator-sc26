"""``compendium wikidata …``: build the local Wikidata index, keep it in step, and report its state (D43, D64).

The index maps article titles of the German Wikipedia to Wikidata numbers and, for the DBpedia URI, to the title of
the English article (D65). It is built from ``page_props``, ``page`` and ``langlinks`` of dumps.wikimedia.org/dewiki:
``build`` reads the dump files on disk and asks nothing online, ``sync`` downloads all three itself when the index is
missing or a newer Wikipedia archive needs a newer one - with ``--loop`` as the ``wikidata-updater`` sidecar. A
running service opens a new index by itself within a minute.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path

from app.cli_sync import run_build, run_sync
from app.settings import get_settings
from app.sources.wikidata.index import WikidataIndex, build_index
from app.sources.wikidata.sync import ALIVE_FILE, LOCK_FILE, build_sync

log = logging.getLogger(__name__)

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
    return run_build(
        target,
        lock_file=LOCK_FILE,
        name="Wikidata-Index",
        build=lambda: build_index(
            Path(args.page_props), Path(args.page), target, langlinks=Path(args.langlinks) if args.langlinks else None
        ),
        describe=lambda meta: f"{meta['articles']} Artikel, Dump vom {meta['dump'] or '?'}",
    )


def cmd_sync(args: argparse.Namespace) -> int:
    settings = get_settings()
    sync = build_sync(settings)
    force = bool(args.force)
    # As the sidecar every message is a log record, so LOG_FORMAT=json makes it a JSON object (review of 2026-10-08);
    # once, the command prints for the person who runs it
    say: Callable[[str], None] = log.info if args.loop else print

    def task() -> None:
        nonlocal force
        reason = sync.due(force=force)
        force = False
        if reason is None:
            say("Wikidata-Index ist aktuell: vorhanden, und kein neueres Wikipedia-Archiv braucht einen neueren Dump")
            return
        say(f"Wikidata-Index wird gebaut ({REASONS.get(reason, reason)}): drei Dumps laden, rund 750 MB")
        meta = sync.run(reason)
        say(f"Wikidata-Index {sync.index_path}: {meta['articles']} Artikel, Dump vom {meta['dump'] or '?'}")

    return run_sync(
        task,
        loop=bool(args.loop),
        interval=settings.wikidata_check_interval,
        name="Wikidata-Index",
        alive=Path(settings.state_dir) / ALIVE_FILE,
    )


def add_wikidata_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("wikidata", help="Wikidata-Index aus Dumps der deutschen Wikipedia: build, sync, status")
    commands = parser.add_subparsers(dest="wikidata_command", required=True)

    status = commands.add_parser("status", help="Stand des Index: Artikel, Datum des Dumps, Quelldateien")
    status.set_defaults(func=cmd_status)

    build = commands.add_parser("build", help="Index aus page_props, page und langlinks bauen (lokale Dateien)")
    build.add_argument("--page-props", required=True, help="dewiki-…-page_props.sql.gz")
    build.add_argument("--page", required=True, help="dewiki-…-page.sql.gz")
    build.add_argument("--langlinks", help="dewiki-…-langlinks.sql.gz: englische Titel für die DBpedia-URIs (D65)")
    build.set_defaults(func=cmd_build)

    sync = commands.add_parser(
        "sync", help="Index bauen, wenn er fehlt oder ein neueres Wikipedia-Archiv einen neueren Dump braucht"
    )
    sync.add_argument("--loop", action="store_true", help="Sidecar: prüfen nach WIKIDATA_CHECK_INTERVAL (1d)")
    sync.add_argument("--force", action="store_true", help="auch einen aktuellen Index neu bauen")
    sync.set_defaults(func=cmd_sync)
