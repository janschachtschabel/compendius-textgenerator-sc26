"""Command line: generate a compendium, list templates, manage archives (``zim`` subcommands)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from app.cli_collection import add_collection_commands
from app.cli_common import cli_service
from app.cli_eval import add_eval_commands
from app.cli_lehrplan import add_lehrplan_commands
from app.cli_zim import add_zim_commands
from app.domain.requests import GenerateRequest
from app.logging import configure_logging
from app.service import PartsUnavailableError, TopicNotFoundError
from app.settings import get_settings
from app.sources.wlo.client import EduSharingError
from app.templates.manager import TemplateManager


def cmd_generate(args: argparse.Namespace) -> int:
    service = cli_service(args.zim)
    try:
        request = GenerateRequest(
            topic=args.topic,
            collection_id=args.collection_id,
            knowledge_collection_id=args.knowledge_collection_id,
            template_id=args.template,
            matcher=args.matcher,
            mode=args.mode,
            target_length=args.length,
            facets_visible=args.facets_visible or None,
        )
    except ValidationError as exc:
        print(f"Ungültige Anfrage: {exc.errors()[0]['msg']}", file=sys.stderr)
        return 1
    try:
        result = service.generate(request)
    except TopicNotFoundError as exc:
        print(f"Thema nicht gefunden: {exc.resolution.normalized}", file=sys.stderr)
        if exc.resolution.alternatives:
            print("Vorschläge: " + ", ".join(exc.resolution.alternatives), file=sys.stderr)
        return 1
    except EduSharingError as exc:
        print(str(exc), file=sys.stderr)  # the message names the repository
        return 1
    except PartsUnavailableError as exc:
        print(f"Kein angefragter Teil ist erzeugbar: {exc}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(result.markdown, encoding="utf-8")
        print(f"Markdown geschrieben: {args.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        print(result.markdown)
    if args.json:
        Path(args.json).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"JSON geschrieben: {args.json}")
    audit = result.audit
    print(
        f"Thema: {result.topic} | Modus: {result.mode} | Quellen: {len(result.sources)} | Chunks: {audit.chunks_total} "
        f"(zugeordnet {audit.chunks_assigned}) | Bausteine gefüllt: {audit.sections_filled}, "
        f"leer: {audit.sections_empty} "
        f"| Belege: {audit.citations} | Zeiten ms: {audit.timings_ms}",
        file=sys.stderr,
    )
    if audit.llm is not None:
        tokens = audit.llm_tokens or {}
        print(
            f"LLM: angefordert {audit.llm['mode_requested']}, verwendet {result.mode} "
            f"| Aufrufe: {tokens.get('calls', 0)} | Tokens: {tokens.get('total', 0)} "
            f"| Bausteine per LLM: {len(audit.llm['sections'])} "
            f"| Rückfälle: {len(audit.llm['fallbacks'])}"
            + (f" | {audit.llm['note']}" if audit.llm.get("note") else ""),
            file=sys.stderr,
        )
    for finding in audit.lint:
        print(f"  lint [{finding.severity}] {finding.section_id}: {finding.message}", file=sys.stderr)
    return 0


def cmd_templates(args: argparse.Namespace) -> int:
    settings = get_settings()
    manager = TemplateManager(custom_dir=Path(settings.state_dir) / "templates")
    for template in manager.list():
        marker = "builtin" if template.builtin else "custom"
        print(f"{template.id:12s} v{template.version}  {len(template.slots):2d} Slots  {marker}  {template.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compendium", description="Kompendium-API v2 Werkzeuge")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Kompendium (Teil 1, Regelmodus) erzeugen")
    gen.add_argument("--topic", default=None, help="Thema; ohne Angabe der Titel der Sammlung")
    gen.add_argument("--collection-id", default=None, help="nodeId der Sammlung (Thema, Fach, Teil 3)")
    gen.add_argument("--knowledge-collection-id", default=None, help="Sammlung, deren OER-Materialien Teil 1 speisen")
    gen.add_argument("--zim", action="append", help="ZIM-Archiv (mehrfach möglich); sonst ZIM_PATHS/ZIM_DIR")
    gen.add_argument("--template", default=None)
    gen.add_argument("--matcher", default=None)
    gen.add_argument(
        "--mode",
        default=None,
        choices=["rule-based", "hybrid-fast", "hybrid-quality"],
        help="Erzeugungsmodus; ohne Angabe LLM_MODE_DEFAULT (Hybridmodi brauchen LLM_ENABLED und B_API_KEY)",
    )
    gen.add_argument("--length", type=int, default=12_000)
    gen.add_argument("--facets-visible", action="store_true")
    gen.add_argument("--out", default=None, help="Markdown-Datei")
    gen.add_argument("--json", default=None, help="JSON-Datei mit dem vollständigen Ergebnis")
    gen.set_defaults(func=cmd_generate)

    add_zim_commands(sub)
    add_eval_commands(sub)
    add_lehrplan_commands(sub)
    add_collection_commands(sub)

    tpl = sub.add_parser("templates", help="Templates auflisten")
    tpl.set_defaults(func=cmd_templates)

    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
