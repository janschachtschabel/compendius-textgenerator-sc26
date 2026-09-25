"""``compendium lehrplan …``: cache status, MEM change check, harvest (once or as the loop), local search."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from app.jobs.runner import parse_interval, run_periodically, stop_on_sigterm
from app.settings import Settings, get_settings
from app.sources.lehrplan.harvest import TRIGGER_FILE, HarvestRunningError, LehrplanHarvest, read_status
from app.sources.lehrplan.matcher import LehrplanMatcher, build_keywords
from app.sources.lehrplan.part import match_entry
from app.sources.lehrplan.render import coverage
from app.sources.lehrplan.sparql import SparqlClient, SparqlError
from app.sources.lehrplan.store import LehrplanCacheError, LehrplanStore
from app.sources.lehrplan.subjects import SubjectCatalog

POLL_SECONDS = 60
# A failed harvest (MEM unreachable, also on a first start without a cache) tries again after an hour rather than
# after LEHRPLAN_CHECK_INTERVAL, as the ZIM loop does
RETRY_AFTER_FAILURE = timedelta(hours=1)


def _harvest(settings: Settings) -> LehrplanHarvest:
    client = SparqlClient(settings.lehrplan_endpoint, pause_s=settings.lehrplan_request_pause_s)
    return LehrplanHarvest(client, settings.lehrplan_db_path, state_dir=Path(settings.state_dir))


def _subjects(settings: Settings) -> SubjectCatalog:
    return SubjectCatalog.load(settings.subjects_path) if settings.subjects_path.exists() else SubjectCatalog.empty()


def cmd_status(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = LehrplanStore(settings.lehrplan_db_path)
    print(f"Lehrplan-Cache: {store.path}")
    if not store.exists:
        print("  kein Lehrplan-Cache vorhanden (compendium lehrplan harvest)")
    elif not store.available:
        print("  Lehrplan-Cache unbrauchbar (fremde Schemaversion oder beschädigte Datei); compendium lehrplan harvest")
    else:
        meta, counts, info = store.meta(), store.counts(), coverage(store.meta())
        print(
            f"  Stand {info['harvested_at']} | {info['lehrplaene_total']} Lehrpläne | {counts['nodes']} Knoten "
            f"| Endpoint {meta.get('endpoint', '?')} | Ontologie {meta.get('ontology_version', '?')}"
        )
        for code, count in counts["lehrplaene"].items():
            print(f"  {code}: {count}")
    status = read_status(Path(settings.state_dir))
    if status:
        print(f"Letzter Harvest-Lauf: {status.get('state')} ({status.get('updated_at')})")
        if status.get("error"):
            print(f"  Fehler: {status['error']}")
        if status.get("state") == "running" and status.get("progress"):
            print(f"  Fortschritt: {status['progress']}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    try:
        result = _harvest(get_settings()).check()
    except SparqlError as exc:
        print(f"MEM nicht erreichbar: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    settings = get_settings()
    harvest = _harvest(settings)
    max_age = parse_interval(settings.lehrplan_harvest_max_age)
    force = bool(args.force)

    def task() -> None:
        nonlocal force
        if force or harvest.due(max_age=max_age):
            force = False
            report = harvest.run()
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        else:
            print("Lehrplan-Cache ist aktuell: MEM-Zählung unverändert und jünger als LEHRPLAN_HARVEST_MAX_AGE")

    if args.loop:
        stop_on_sigterm()
        try:
            run_periodically(
                task,
                parse_interval(settings.lehrplan_check_interval),
                retry_after=RETRY_AFTER_FAILURE,
                poll_s=POLL_SECONDS,
                trigger_file=Path(settings.state_dir) / TRIGGER_FILE,
            )
        except KeyboardInterrupt:  # Ctrl+C or a container stop; the harvest has written its status
            print("Harvest-Schleife beendet.")
        return 0
    try:
        task()
    except HarvestRunningError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except SparqlError as exc:
        print(f"Harvest abgebrochen, alter Cache bleibt: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = LehrplanStore(settings.lehrplan_db_path)
    if not store.available:
        print("kein brauchbarer Lehrplan-Cache vorhanden (compendium lehrplan harvest)", file=sys.stderr)
        return 1
    keywords = build_keywords(args.q, aliases=[], subtopics=[])
    try:
        result = LehrplanMatcher(store).match(keywords, subject_terms=_subjects(settings).mem_terms(args.subject))
    except LehrplanCacheError as exc:
        print(f"Lehrplan-Cache nicht lesbar ({exc}); compendium lehrplan harvest --force", file=sys.stderr)
        return 1
    print(
        f"{len(result.matches)} Treffer ({result.excluded_noise} als Wortfragment ausgeschlossen) "
        f"für {', '.join(result.keywords)}"
        + (f" im Fach {', '.join(result.subject_terms)}" if result.subject_terms else "")
    )
    for match in result.matches[: args.limit]:
        entry = match_entry(match)
        print(
            f"  [{entry['bundesland_code']}] {entry['schulstufe']:16s} {entry['klassenstufe']:24s} {entry['label']}"
            f"  ({', '.join(entry['rollen'])}; {entry['lehrplan']}; {entry['bereich']})"
        )
    if args.json:
        Path(args.json).write_text(
            json.dumps([match_entry(match) for match in result.matches], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON geschrieben: {args.json}")
    return 0


def add_lehrplan_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("lehrplan", help="Lehrplan-Cache aus MEM: status, check, harvest, search")
    commands = parser.add_subparsers(dest="lehrplan_command", required=True)

    status = commands.add_parser("status", help="Cache-Stand, Lehrpläne je Land, letzter Harvest-Lauf")
    status.set_defaults(func=cmd_status)

    check = commands.add_parser("check", help="MEM-Zählung je Land mit dem letzten Harvest vergleichen")
    check.set_defaults(func=cmd_check)

    harvest = commands.add_parser("harvest", help="Vollabzug aus MEM in den Cache (wenn fällig)")
    harvest.add_argument("--loop", action="store_true", help="Harvest-Sidecar: wöchentlich prüfen plus Trigger-Datei")
    harvest.add_argument("--force", action="store_true", help="auch ohne Änderung neu ziehen")
    harvest.set_defaults(func=cmd_harvest)

    search = commands.add_parser("search", help="Lehrplanelemente zu einem Stichwort aus dem Cache")
    search.add_argument("--q", required=True, help="Thema oder Stichwort")
    search.add_argument("--subject", default=None, help="Fach (WLO-ID, URI, Label oder Alias)")
    search.add_argument("--limit", type=int, default=30)
    search.add_argument("--json", default=None, help="Treffer als JSON-Datei")
    search.set_defaults(func=cmd_search)
