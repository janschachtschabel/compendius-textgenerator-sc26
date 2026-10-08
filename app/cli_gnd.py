"""``compendium gnd …``: build the local GND index, keep it in step with the DNB's releases, report its state (D65).

The index gives an article without a Normdaten block the GND record that names its Wikidata item or carries its title.
It is built from the DNB's dumps of the subject headings and the places: ``build`` reads two files on disk and asks
nothing online, ``sync`` downloads them itself when the index is missing or a newer release is out - with ``--loop``
as the ``gnd-updater`` sidecar. A running service opens a new index by itself within a minute.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.cli_sync import run_build, run_sync
from app.settings import get_settings
from app.sources.gnd.index import GndIndex, build_gnd_index
from app.sources.gnd.sync import ALIVE_FILE, KINDS, LOCK_FILE, build_gnd_sync

log = logging.getLogger(__name__)

REASONS = {
    "no index": "kein Index vorhanden",
    "index unusable": "Index unbrauchbar",
    "newer release": "neuere Ausgabe der DNB",
    "forced": "erzwungen",
}


def _describe(meta: dict[str, Any]) -> str:
    return f"{meta['records']} Datensätze, Release {meta['release'] or '?'}"


def cmd_status(args: argparse.Namespace) -> int:
    index = GndIndex(get_settings().gnd_db_path)
    print(f"GND-Index: {index.path}")
    if not index.exists:
        print("  kein GND-Index vorhanden (compendium gnd sync, ohne Netz: build)")
    elif not index.available:
        print("  GND-Index unbrauchbar (fremdes Schema, beschädigte Datei); compendium gnd sync --force")
    else:
        meta = index.meta()
        print(
            f"  {_describe(meta)} | {meta['items']} Wikidata-Objekte, {meta['names']} eindeutige Namen "
            f"| gebaut {meta['built_at']} | aus {', '.join(meta['sources'])}"
        )
    index.close()
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    target = get_settings().gnd_db_path
    files = [Path(args.sachbegriff), Path(args.geografikum)]
    return run_build(
        target,
        lock_file=LOCK_FILE,
        name="GND-Index",
        build=lambda: build_gnd_index(list(zip(files, [kind for _, kind in KINDS], strict=True)), target),
        describe=_describe,
    )


def cmd_sync(args: argparse.Namespace) -> int:
    settings = get_settings()
    sync = build_gnd_sync(settings)
    force = bool(args.force)
    # As the sidecar every message is a log record, so LOG_FORMAT=json makes it a JSON object (review of 2026-10-08);
    # once, the command prints for the person who runs it
    say: Callable[[str], None] = log.info if args.loop else print

    def task() -> None:
        nonlocal force
        reason = sync.due(force=force)
        force = False
        if reason is None:
            say("GND-Index ist aktuell: vorhanden und aus der neuesten Ausgabe der DNB")
            return
        say(f"GND-Index fällig ({REASONS.get(reason, reason)}): zwei Abzüge der DNB laden, rund 65 MB")
        meta = sync.run(reason)
        say(f"GND-Index {sync.index_path}: {_describe(meta)}")

    return run_sync(
        task,
        loop=bool(args.loop),
        interval=settings.gnd_check_interval,
        name="GND-Index",
        alive=Path(settings.state_dir) / ALIVE_FILE,
    )


def add_gnd_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("gnd", help="GND-Index aus den Abzügen der DNB: build, sync, status")
    commands = parser.add_subparsers(dest="gnd_command", required=True)

    status = commands.add_parser("status", help="Stand des Index: Datensätze, Release, Quelldateien")
    status.set_defaults(func=cmd_status)

    build = commands.add_parser("build", help="Index aus den Abzügen auf der Platte bauen (kein Netz)")
    build.add_argument("--sachbegriff", required=True, help="authorities-gnd-sachbegriff_lds_….ttl.gz")
    build.add_argument("--geografikum", required=True, help="authorities-gnd-geografikum_lds_….ttl.gz")
    build.set_defaults(func=cmd_build)

    sync = commands.add_parser("sync", help="Index bauen, wenn er fehlt oder die DNB eine neuere Ausgabe hat")
    sync.add_argument("--loop", action="store_true", help="Sidecar: prüfen nach GND_CHECK_INTERVAL (1d)")
    sync.add_argument("--force", action="store_true", help="auch einen aktuellen Index neu bauen")
    sync.set_defaults(func=cmd_sync)
