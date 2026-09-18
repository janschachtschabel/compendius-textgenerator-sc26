"""``compendium eval …``: export chunks for labelling, import reviewed CSVs, run the evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.cli_common import cli_service
from app.matching.eval import EvalResult
from app.matching.eval_runner import DEFAULT_MATCHERS, EvalReport, evaluate_gold_dir, export_topic
from app.matching.gold import import_csv, save_gold
from app.service import TopicNotFoundError
from app.settings import get_settings
from app.templates.manager import TemplateManager


def _slug(topic: str) -> str:
    table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", " ": "_"})
    return "".join(ch for ch in topic.lower().translate(table) if ch.isalnum() or ch == "_")


def cmd_export(args: argparse.Namespace) -> int:
    service = cli_service(args.zim)
    out = Path(args.out or f"eval/export/{_slug(args.topic)}.csv")
    try:
        path, count = export_topic(service, args.topic, out, template_id=args.template, matcher=args.matcher)
    except TopicNotFoundError as exc:
        print(f"Thema nicht gefunden: {exc.resolution.normalized}", file=sys.stderr)
        return 1
    print(f"{count} Chunks nach {path} geschrieben; Spalte gold_slot ausfüllen (Slot-Key, none oder leer).")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    settings = get_settings()
    template = TemplateManager(custom_dir=Path(settings.state_dir) / "templates").get(args.template or "sc26")
    slot_keys = [slot.slot for slot in template.content_slots()]
    gold = import_csv(
        Path(args.csv),
        topic=args.topic,
        slot_keys=slot_keys,
        template_id=template.id,
        labeled_by=args.labeled_by or "",
        zim=cli_service(args.zim).registry.snapshot(),
    )
    out = save_gold(Path(args.out or settings.eval_gold_dir / f"{_slug(args.topic)}.jsonl"), gold)
    labelled = sum(1 for label in gold.labels if label.slot)
    print(f"{len(gold.labels)} Labels ({labelled} mit Baustein, {len(gold.labels) - labelled} none) -> {out}")
    return 0


def _print_result(result: EvalResult) -> None:
    hallucinated = ", ".join(result.hallucination_slots) or "-"
    print(
        f"{result.matcher:14s} macro-F1 {result.macro_f1:.3f}  micro-F1 {result.micro_f1:.3f}  "
        f"zugeordnet {result.assigned}/{result.labeled}  fehlbelegt {result.misassigned}  verpasst {result.missed}  "
        f"Halluzination: {hallucinated}  veraltete Labels {result.stale_labels}  {result.duration_ms} ms"
    )


def _print_slots(result: EvalResult) -> None:
    print(f"  {'Baustein':28s} {'Gold':>5s} {'Zug.':>5s} {'P':>6s} {'R':>6s} {'F1':>6s}")
    for metrics in result.slots:
        if metrics.support or metrics.predicted:
            print(
                f"  {metrics.slot:28s} {metrics.support:5d} {metrics.predicted:5d} "
                f"{metrics.precision:6.2f} {metrics.recall:6.2f} {metrics.f1:6.2f}"
            )


def _report_dict(report: EvalReport, gold_dir: Path, matchers: list[str]) -> dict[str, Any]:
    return {
        "gold_dir": str(gold_dir),
        "matchers": matchers,
        "skipped": report.skipped,
        "runs": [
            {
                "topic": run.topic,
                "labeled": len(run.alignment.gold_by_chunk),
                "stale": len(run.alignment.stale),
                "results": {name: result.model_dump() for name, result in run.results.items()},
            }
            for run in report.runs
        ],
        "aggregate": {name: result.model_dump() for name, result in report.aggregate.items()},
    }


def cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    gold_dir = Path(args.gold or settings.eval_gold_dir)
    matchers = list(args.matcher or DEFAULT_MATCHERS)
    report = evaluate_gold_dir(cli_service(args.zim), gold_dir, matchers, template_id=args.template)
    if not report.runs:
        print(f"Keine auswertbaren Gold-Dateien in {gold_dir} (übersprungen: {report.skipped})", file=sys.stderr)
        return 2
    print(f"Goldstandard {gold_dir}: {len(report.runs)} Themen, übersprungen: {report.skipped or '-'}")
    for name in matchers:
        if name in report.aggregate:
            _print_result(report.aggregate[name])
    detail = report.aggregate.get(args.detail or matchers[-1])
    if detail is not None:
        print(f"Bausteine ({detail.matcher}, Klassifikation vor Budget, alle Themen gepoolt):")
        _print_slots(detail)
        top = list(detail.confusion.items())[:12]
        if top:
            print("  häufigste Verwechslungen (Gold>Zuordnung): " + ", ".join(f"{k} {v}" for k, v in top))
    best = report.aggregate.get(matchers[0])
    print("Je Thema (macro-F1):")
    for run in report.runs:
        cells = "  ".join(f"{name} {run.results[name].macro_f1:.2f}" for name in matchers if name in run.results)
        print(f"  {run.topic:24s} {cells}")
    if args.json:
        Path(args.json).write_text(json.dumps(_report_dict(report, gold_dir, matchers), ensure_ascii=False, indent=2))
        print(f"Bericht: {args.json}")
    if args.min_f1 is not None and best is not None and best.macro_f1 < args.min_f1:
        print(
            f"macro-F1 {best.macro_f1:.3f} von {best.matcher} liegt unter der Schwelle {args.min_f1}", file=sys.stderr
        )
        return 1
    return 0


def add_eval_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    ev = sub.add_parser("eval", help="Goldstandard: Chunks exportieren, Labels importieren, Matcher bewerten")
    ev_sub = ev.add_subparsers(dest="eval_command", required=True)

    export = ev_sub.add_parser("export", help="Chunks eines Themas als CSV zum Labeln schreiben")
    export.add_argument("--topic", required=True)
    export.add_argument("--out", default=None, help="CSV-Datei (Standard eval/export/<thema>.csv)")
    export.add_argument("--template", default=None)
    export.add_argument("--matcher", default=None, help="Strategie für die Vorschlagsspalte")
    export.add_argument("--zim", action="append", help="ZIM-Archiv (mehrfach möglich); sonst ZIM_PATHS/ZIM_DIR")
    export.set_defaults(func=cmd_export)

    imp = ev_sub.add_parser("import", help="geprüfte CSV als Gold-Datei (JSONL) speichern")
    imp.add_argument("csv")
    imp.add_argument("--topic", required=True)
    imp.add_argument("--out", default=None, help="JSONL-Datei (Standard EVAL_GOLD_DIR/<thema>.jsonl)")
    imp.add_argument("--template", default=None)
    imp.add_argument("--labeled-by", default=None)
    imp.add_argument("--zim", action="append")
    imp.set_defaults(func=cmd_import)

    run = ev_sub.add_parser("run", help="alle Gold-Dateien mit einer oder mehreren Strategien bewerten")
    run.add_argument("--gold", default=None, help="Verzeichnis mit *.jsonl (Standard EVAL_GOLD_DIR)")
    run.add_argument("--matcher", action="append", help="Strategie (mehrfach); Standard: alle eingebauten")
    run.add_argument("--template", default=None)
    run.add_argument("--json", default=None, help="Bericht als JSON-Datei")
    run.add_argument("--min-f1", type=float, default=None, help="Exit 1, wenn die erste Strategie darunter bleibt")
    run.add_argument("--detail", default=None, help="Strategie für die Baustein-Tabelle (Standard: letzte)")
    run.add_argument("--zim", action="append")
    run.set_defaults(func=cmd_run)
