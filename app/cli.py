"""Command line: generate a compendium, list templates, manage archives (``zim`` subcommands)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.cli_collection import add_collection_commands
from app.cli_common import cli_service
from app.cli_eval import add_eval_commands
from app.cli_lehrplan import add_lehrplan_commands
from app.cli_wikidata import add_wikidata_commands
from app.cli_zim import add_zim_commands
from app.domain.requests import MATCHERS, PRESETS, GenerateRequest
from app.logging import configure_logging
from app.service import PartsUnavailableError, TopicNotFoundError
from app.settings import get_settings
from app.sources.wlo.client import EduSharingError
from app.templates.manager import TemplateManager, TemplateNotFoundError
from app.templates.schema import Template


def cmd_generate(args: argparse.Namespace) -> int:
    service = cli_service(args.zim)
    try:
        request = GenerateRequest(
            topic=args.topic,
            collection_id=args.collection_id,
            knowledge_collection_id=args.knowledge_collection_id,
            template_id=args.template,
            preset=args.preset,
            matcher=args.matcher,
            article_choice=args.article_choice,
            extraction=args.extraction,
            generation=args.generation,
            enrichment=args.enrichment,
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
    except TemplateNotFoundError as exc:
        print(f"Template nicht gefunden: {exc.args[0]}", file=sys.stderr)
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
    veredelt = f"| Veredlung: {result.enrichment} " if result.enrichment != "sources-only" else ""
    stufe = f"| Stufe: {audit.preset} " if audit.preset else ""
    print(
        f"Thema: {result.topic} {stufe}| Extraktion: {result.extraction} | Generierung: {result.generation} "
        f"{veredelt}"
        f"| Quellen: {len(result.sources)} "
        f"| Chunks: {audit.chunks_total} "
        f"(zugeordnet {audit.chunks_assigned}) | Bausteine gefüllt: {audit.sections_filled}, "
        f"leer: {audit.sections_empty} "
        f"| Belege: {audit.citations} | Zeiten ms: {audit.timings_ms}",
        file=sys.stderr,
    )
    if audit.llm is not None:
        tokens = audit.llm_tokens or {}
        extraction, generation = audit.llm["extraction"], audit.llm["generation"]
        fallbacks = len(extraction["fallbacks"]) + len(generation["fallbacks"])
        print(
            f"LLM: Extraktion angefordert {extraction['requested']}, verwendet {extraction['used']} "
            f"| Generierung angefordert {generation['requested']}, verwendet {generation['used']} "
            f"| Aufrufe: {tokens.get('calls', 0)} | Tokens: {tokens.get('total', 0)} "
            f"| Bausteine ausgewählt: {len(extraction['sections'])}, geschrieben: {len(generation['sections'])} "
            f"| Rückfälle: {fallbacks}" + (f" | {audit.llm['note']}" if audit.llm.get("note") else ""),
            file=sys.stderr,
        )
    for finding in audit.lint:
        print(f"  lint [{finding.severity}] {finding.section_id}: {finding.message}", file=sys.stderr)
    return 0


def template_manager() -> TemplateManager:
    return TemplateManager(custom_dir=Path(get_settings().state_dir) / "templates")


def cmd_templates(args: argparse.Namespace) -> int:
    for template in template_manager().list():
        marker = "builtin" if template.builtin else "custom"
        print(f"{template.id:12s} v{template.version}  {len(template.slots):2d} Slots  {marker}  {template.name}")
    return 0


def cmd_templates_save(args: argparse.Namespace) -> int:
    """Store a template from a JSON file; the version counts up when the id is already there."""
    path = Path(args.file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        template = Template.model_validate({**data, "builtin": False})
    except (OSError, ValueError, ValidationError) as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1
    try:
        stored = template_manager().save(template)
    except ValueError as exc:  # a built-in id is read-only; the message says what to do instead
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{stored.id} v{stored.version} gespeichert ({len(stored.slots)} Slots)")
    return 0


def cmd_templates_delete(args: argparse.Namespace) -> int:
    try:
        removed = template_manager().delete(args.template_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not removed:
        print(f"Template nicht gefunden: {args.template_id}", file=sys.stderr)
        return 1
    print(f"{args.template_id} gelöscht")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compendium", description="Kompendium-API v2 Werkzeuge")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser(
        "generate", help="Kompendium erzeugen: alle Teile, die sich erzeugen lassen; Stufe und LLM-Schalter wie die API"
    )
    gen.add_argument("--topic", default=None, help="Thema; ohne Angabe der Titel der Sammlung")
    gen.add_argument("--collection-id", default=None, help="nodeId der Sammlung (Thema, Fach, Teil 3)")
    gen.add_argument("--knowledge-collection-id", default=None, help="Sammlung, deren OER-Materialien Teil 1 speisen")
    gen.add_argument("--zim", action="append", help="ZIM-Archiv (mehrfach möglich); sonst ZIM_PATHS/ZIM_DIR")
    gen.add_argument("--template", default=None)
    gen.add_argument(
        "--preset",
        default=None,
        choices=list(PRESETS),
        help="Stufe der Entscheidungsvorlage: llm-free (wie ohne Angabe), balanced (LLM wählt die Artikel), "
        "best-quality (LLM ordnet auch zu); einzeln gesetzte Schalter gehen vor",
    )
    gen.add_argument(
        "--matcher",
        default=None,
        choices=list(MATCHERS),
        help="Wie die Absätze ihren Baustein finden; ohne Angabe MATCHER_DEFAULT (llm braucht LLM_ENABLED und "
        "B_API_KEY)",
    )
    gen.add_argument(
        "--article-choice",
        default=None,
        choices=["rule-based", "llm"],
        help="Wer bei unsicherer Artikelwahl entscheidet; ohne Angabe LLM_ARTICLE_CHOICE_DEFAULT, ausgeliefert "
        "rule-based (llm braucht LLM_ENABLED und B_API_KEY)",
    )
    gen.add_argument(
        "--extraction",
        default=None,
        choices=["rule-based", "llm"],
        help="Wer die Sätze der Bausteine auswählt; ohne Angabe LLM_EXTRACTION_DEFAULT (llm braucht LLM_ENABLED "
        "und B_API_KEY)",
    )
    gen.add_argument(
        "--generation",
        default=None,
        choices=["rule-based", "llm-fast", "llm"],
        help="Wer die Bausteine schreibt; ohne Angabe LLM_GENERATION_DEFAULT (llm-fast und llm brauchen "
        "LLM_ENABLED und B_API_KEY)",
    )
    gen.add_argument(
        "--enrichment",
        default=None,
        choices=["sources-only", "model-knowledge"],
        help="Ob das Modell eigenes Wissen ergänzen darf; ohne Angabe LLM_ENRICHMENT_DEFAULT. Ergänzte Sätze "
        "stehen im Text als Evidenzgrad=Modellwissen und brauchen --generation llm oder llm-fast",
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
    add_wikidata_commands(sub)

    tpl = sub.add_parser("templates", help="Templates auflisten, speichern, löschen")
    tpl.set_defaults(func=cmd_templates)  # the bare command keeps listing, as it always did
    tpl_sub = tpl.add_subparsers(dest="templates_command")

    tpl_save = tpl_sub.add_parser("save", help="Template aus einer JSON-Datei speichern")
    tpl_save.add_argument("file", help="JSON-Datei mit dem Template")
    tpl_save.set_defaults(func=cmd_templates_save)

    tpl_delete = tpl_sub.add_parser("delete", help="eigenes Template löschen (eingebaute bleiben)")
    tpl_delete.add_argument("template_id", help="id des Templates")
    tpl_delete.set_defaults(func=cmd_templates_delete)

    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
