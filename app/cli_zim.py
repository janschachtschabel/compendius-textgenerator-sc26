"""``compendium zim …``: status, catalog, sync (once or as the updater loop), archive metadata."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from app.jobs.runner import parse_interval, run_periodically, stop_on_sigterm
from app.jobs.zim_sync import (
    TRIGGER_FILE,
    SyncOptions,
    SyncReport,
    SyncRunningError,
    ZimSync,
    build_sync,
    read_status,
)
from app.settings import get_settings
from app.sources.zim.active import read_active
from app.sources.zim.archive import ZimArchive
from app.sources.zim.catalog import OPDS_DEFAULT_URL, KiwixCatalog
from app.sources.zim.subscriptions import load_manifest

POLL_SECONDS = 60
# A run that aborted, or whose downloads stopped on the way (network, full volume), is tried again after an hour,
# not after ZIM_SYNC_INTERVAL (30 days); the next run resumes the .part. Hash or size mismatches and archives
# libzim cannot open wait for the interval, so a broken file is not fetched every hour.
RETRY_AFTER_FAILURE = timedelta(hours=1)


def _gb(size: int) -> str:
    return f"{size / 1e9:.2f} GB"


def cmd_status(args: argparse.Namespace) -> int:
    settings = get_settings()
    manifest = load_manifest(settings.zim_manifest_path)
    required = settings.zim_required_ids or manifest.required_ids(settings.zim_profile)
    print(f"ZIM-Verzeichnis: {settings.zim_dir} | Profil: {settings.zim_profile}")
    state = read_active(settings.zim_dir)
    if state is None:
        print("active.json fehlt: noch kein Sync gelaufen (compendium zim sync)")
    else:
        for archive in state.archives.values():
            print(f"  aktiv    {archive.id:30s} {archive.file}  {archive.date}  {_gb(archive.size)}")
        for retired in state.retired:
            print(f"  abgelöst {retired.file}  seit {retired.retired_at}")
    present = set(state.archives) if state else set()
    for archive_id in required:
        if archive_id not in present:
            print(f"  FEHLT    {archive_id} (Pflichtarchiv, /ready bleibt 503)")
    status = read_status(settings.zim_dir)
    if status:
        print(f"Letzter Sync: {status.get('state')} ({status.get('updated_at')})")
        download = status.get("download")
        if download:
            print(f"  Download {download.get('file')}: {download.get('percent')} % ({download.get('speed_mb_s')} MB/s)")
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    settings = get_settings()
    manifest = load_manifest(settings.zim_manifest_path)
    catalog = KiwixCatalog(settings.zim_catalog_url or OPDS_DEFAULT_URL)
    try:
        if args.all:
            entries = catalog.entries()
        else:
            entries = []
            for sub in manifest.for_profile(settings.zim_profile):
                entry = catalog.latest(sub.name, sub.flavour)
                if entry is None:
                    print(f"  nicht im Katalog: {sub.id}")
                else:
                    entries.append(entry)
    finally:
        catalog.close()
    for entry in entries:
        fulltext = "Volltextindex" if entry.has_fulltext else ""
        print(
            f"{entry.archive_id:34s} {entry.file_name:46s} {_gb(entry.size):>10s} "
            f"{entry.article_count:>10d} Artikel  {fulltext}"
        )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    settings = get_settings()
    sync = build_sync(settings, offline=args.offline)
    options = SyncOptions(
        profile=args.profile or settings.zim_profile,
        download_missing=args.download_missing or settings.zim_bootstrap_download,
    )
    if not args.loop:
        try:
            report = sync.run(options)
        except SyncRunningError as exc:
            print(f"{exc}; der Updater setzt den Lauf fort.", file=sys.stderr)
            return 1
        _print_report(report)
        return 1 if report.errors else 0
    interval = parse_interval(settings.zim_sync_interval)
    trigger = Path(settings.zim_dir) / TRIGGER_FILE
    print(f"Sync-Schleife: Profil {options.profile}, Intervall {settings.zim_sync_interval}, Trigger-Datei {trigger}")
    stop_on_sigterm()
    try:
        run_periodically(
            lambda: _run_once(sync, options),
            interval,
            retry_after=RETRY_AFTER_FAILURE,
            poll_s=POLL_SECONDS,
            trigger_file=trigger,
        )
    except KeyboardInterrupt:
        print("Sync-Schleife beendet.")
    return 0


def _run_once(sync: ZimSync, options: SyncOptions) -> bool:
    """One loop run; ``False`` asks the loop for the early retry."""
    report = sync.run(options)
    _print_report(report)
    return not report.retry_soon


def _print_report(report: SyncReport) -> None:
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


def cmd_info(args: argparse.Namespace) -> int:
    for path in args.paths:
        print(json.dumps(ZimArchive(Path(path)).snapshot(), ensure_ascii=False, indent=2))
    return 0


def add_zim_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    zim = sub.add_parser("zim", help="ZIM-Archive: Status, Katalog, Sync, Metadaten")
    zim_sub = zim.add_subparsers(dest="zim_command", required=True)

    status = zim_sub.add_parser("status", help="aktive Archive, fehlende Pflichtarchive, letzter Sync")
    status.set_defaults(func=cmd_status)

    catalog = zim_sub.add_parser("catalog", help="Kiwix-Katalog: neueste Dumps der abonnierten Archive")
    catalog.add_argument("--all", action="store_true", help="alle deutschsprachigen Archive des Katalogs")
    catalog.set_defaults(func=cmd_catalog)

    sync = zim_sub.add_parser("sync", help="Archive abgleichen: übernehmen, laden, umschalten, aufräumen")
    sync.add_argument(
        "--loop", action="store_true", help="dauerhaft laufen (Updater-Sidecar), Intervall ZIM_SYNC_INTERVAL"
    )
    sync.add_argument(
        "--download-missing", action="store_true", help="fehlende Pflichtarchive laden (wie ZIM_BOOTSTRAP_DOWNLOAD)"
    )
    sync.add_argument("--offline", action="store_true", help="kein Katalogzugriff, nur lokale Dateien übernehmen")
    sync.add_argument("--profile", default=None, help="Profil aus dem Manifest, sonst ZIM_PROFILE")
    sync.set_defaults(func=cmd_sync)

    info = zim_sub.add_parser("info", help="Metadaten einzelner ZIM-Dateien")
    info.add_argument("paths", nargs="+")
    info.set_defaults(func=cmd_info)
