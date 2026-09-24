"""``compendium wikidata …``: build the local Wikidata index from dump files on disk, and report its state (D43).

The index maps article titles of the German Wikipedia to Wikidata numbers. It is built from ``page_props`` and
``page`` of dumps.wikimedia.org/dewiki, which the operator downloads; this command reads them and asks nothing
online. A running service opens the index at start, so it sees a new one after a restart.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from app.settings import get_settings
from app.sources.wikidata.index import WikidataIndex, build_index


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
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Wikidata-Index nicht gebaut: {exc}", file=sys.stderr)
        return 1
    print(
        f"Wikidata-Index {target}: {meta['articles']} Artikel, Dump vom {meta['dump'] or '?'}, "
        f"{time.monotonic() - started:.0f} s; der Dienst liest ihn nach einem Neustart"
    )
    return 0


def add_wikidata_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("wikidata", help="Wikidata-Index aus Dumps der deutschen Wikipedia: build, status")
    commands = parser.add_subparsers(dest="wikidata_command", required=True)

    status = commands.add_parser("status", help="Stand des Index: Artikel, Datum des Dumps, Quelldateien")
    status.set_defaults(func=cmd_status)

    build = commands.add_parser("build", help="Index aus page_props und page bauen (lokale Dateien, kein Netz)")
    build.add_argument("--page-props", required=True, help="dewiki-…-page_props.sql.gz")
    build.add_argument("--page", required=True, help="dewiki-…-page.sql.gz")
    build.set_defaults(func=cmd_build)
