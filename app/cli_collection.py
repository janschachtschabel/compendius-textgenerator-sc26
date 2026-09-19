"""``compendium collection overview <id>``: part 3 for one collection from the repository."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.settings import get_settings
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError, validate_node_id


def cmd_overview(args: argparse.Namespace) -> int:
    try:
        validate_node_id(args.collection_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    from app.main import build_collections  # not at import time: see cli_common.cli_service

    builder = build_collections(get_settings())
    if builder is None:
        print("kein edu-sharing-Repository konfiguriert (EDU_SHARING_BASE_URL)", file=sys.stderr)
        return 1
    try:
        part = builder.overview(args.collection_id)
    except CollectionNotFoundError as exc:
        print(f"Sammlung nicht gefunden: {exc}", file=sys.stderr)
        return 1
    except EduSharingError as exc:
        print(f"edu-sharing nicht erreichbar: {exc}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(part.markdown, encoding="utf-8")
        print(f"Markdown geschrieben: {args.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        print(part.markdown)
    summary = part.summary
    print(
        f"{part.title}: {summary.get('materials', 0)} Inhalte, {summary.get('subcollections', 0)} Untersammlungen"
        f" | Lizenzen: {summary.get('licenses', {})}"
    )
    return 0


def add_collection_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("collection", help="Sammlungsüberblick (Teil 3) aus dem edu-sharing-Repository")
    commands = parser.add_subparsers(dest="collection_command", required=True)
    overview = commands.add_parser("overview", help="Teil 3 für eine Sammlung erzeugen")
    overview.add_argument("collection_id", help="nodeId der Sammlung")
    overview.add_argument("--out", default=None, help="Markdown-Datei")
    overview.set_defaults(func=cmd_overview)
