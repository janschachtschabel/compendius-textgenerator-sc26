"""Point 5 of the decision paper (M35): should article_choice=llm also check sure resolutions of ambiguous words?

Every query of eval/artikelwahl runs through choose_main_article, the resolution step of the service, four times:

- rules: the rules alone (llm-free);
- balanced: the LLM decides where the rules are unsure (D35), as the service does today;
- A: the LLM also checks a sure resolution that went through a disambiguation page;
- B: as A, and also a sure exact title for which "<title> (Begriffsklärung)" exists.

The model sees the candidates it sees for an unsure resolution (ZimRegistry._let_choose): the meanings of the
disambiguation page, or the rules' article first and then the meanings. A resolution is correct when its title is one
of the expected titles or the target of a redirect Wikipedia sets for one of them. The b-api answers a prompt it has
seen before from its cache (same answer, same reported tokens, 0.1 to 0.3 s): the seconds of a call count only where
the prompt is new, which the output marks per query and variant.

The output holds titles, flags, calls, tokens and seconds, no article text.

With --dry the model is not asked: a stand-in counts the candidates it would see and keeps the rules' article, so
the extra calls of A and B are known before any token is spent.

Usage: python mc_sichere_aufloesung.py <out.json> [--dry] <gold.yaml>...
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import app.knowledge.main_article as main_article  # noqa: E402
from app.cli_common import cli_service  # noqa: E402
from app.domain.models import Resolution  # noqa: E402
from app.knowledge.article_choice import ArticleChoiceJob, ArticleChoiceReport  # noqa: E402
from app.knowledge.main_article import choose_main_article  # noqa: E402
from app.sources.zim.registry import MAX_MEANINGS, ZimRegistry  # noqa: E402
from app.sources.zim.topic_rules import listed_meanings  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
VARIANTS = ("rules", "balanced", "A", "B")

DRY = "--dry" in sys.argv
out_path, gold_paths = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:] if p != "--dry"]
service = cli_service(ZIMS)
if service.llm is None:
    raise SystemExit("LLM_ENABLED did not reach the settings")
wiki = service.registry.primary_archive
TODAY = ZimRegistry.resolve_topic


class DryChooser:
    """--dry: sees the candidates like the model would and keeps the rules' article."""

    def __init__(self, job: ArticleChoiceJob, topic: str, subjects: Sequence[str]) -> None:
        self.report = ArticleChoiceReport()

    def __call__(self, candidates: Sequence[tuple[str, str]]) -> tuple[int | None, str | None]:
        self.report.offered = len(candidates)
        return None, None


if DRY:
    main_article.LlmArticleChooser = DryChooser  # type: ignore[misc,assignment]


def accepted(titles: list[str]) -> list[str]:
    found = list(titles)
    for title in titles:
        # read_article: a gold title may be a redirect to a section ("Elektrischer Leiter" -> Leiter (Physik)), M35
        article = wiki.read_article(title) if wiki is not None else None
        if article is not None and article.title not in found:
            found.append(article.title)
    return found


def disambiguation_of(registry: ZimRegistry, resolution: Resolution) -> list[str]:
    """B: the meanings of "<title> (Begriffsklärung)" for a sure exact title, or none."""
    if resolution.method not in {"title", "variant"}:
        return []
    archive = next((a for a in registry.archives if a.project == resolution.project), None)
    page = archive.read(f"{resolution.title} (Begriffsklärung)") if archive is not None else None
    if page is None:
        return []
    parsed = archive.parse(page)
    return listed_meanings(parsed)[:MAX_MEANINGS] if parsed.is_disambiguation else []


def checking(width: str) -> Callable[..., Resolution]:
    """resolve_topic as the service has it, with the LLM also asked for a sure resolution of an ambiguous word."""

    def resolve_topic(
        self: ZimRegistry,
        topic: str,
        context: Sequence[str] = (),
        query: str | None = None,
        terms: Sequence[str] = (),
        chooser: Any = None,
    ) -> Resolution:
        resolution = self._resolve_by_rules(topic, context, query, terms)
        if chooser is None or not resolution.resolved:
            return resolution
        if not resolution.confident or resolution.disambiguation:
            self._let_choose(resolution, chooser)
        elif width == "B":
            meanings = disambiguation_of(self, resolution)
            if meanings:
                resolution._meanings = meanings
                self._let_choose(resolution, chooser)
        return resolution

    return resolve_topic


def run(query: str, variant: str) -> dict[str, Any]:
    ZimRegistry.resolve_topic = TODAY if variant in {"rules", "balanced"} else checking(variant)  # type: ignore[method-assign]
    job = ArticleChoiceJob(service.llm.client, service.llm.open_budget()) if variant != "rules" else None
    started = time.perf_counter()
    chosen = choose_main_article(service.registry, service.subjects, query, [], job=job)
    seconds = time.perf_counter() - started
    report = chosen.choice
    return {
        "titel": chosen.resolution.title,
        "methode": chosen.resolution.method,
        "sicher": chosen.resolution.confident,
        "begriffsklaerung": chosen.resolution.disambiguation,
        "gefragt": bool(report and report.offered),
        "kandidaten": report.offered if report else 0,
        "benannt": report.named if report else None,
        "tokens": report.total_tokens if report else 0,
        "modell": report.model if report else None,
        "sekunden": round(seconds, 2),
    }


results: dict[str, list[dict[str, Any]]] = {}
seen_prompts: set[tuple[str, str]] = set()  # (query, rules title) already sent: a repeat comes from the cache
for gold_path in gold_paths:
    rows = results.setdefault(gold_path.name, [])
    for entry in yaml.safe_load(gold_path.read_text(encoding="utf-8"))["anfragen"]:
        ok_titles = accepted(entry["erwartet"])
        row: dict[str, Any] = {"anfrage": entry["anfrage"], "art": entry["art"], "akzeptiert": ok_titles}
        for variant in VARIANTS:
            outcome = run(entry["anfrage"], variant)
            outcome["richtig"] = outcome["titel"] in ok_titles
            key = (entry["anfrage"], row.get("rules", {}).get("titel", ""))
            outcome["neu_gefragt"] = outcome["gefragt"] and key not in seen_prompts
            if outcome["gefragt"]:
                seen_prompts.add(key)
            row[variant] = outcome
        rows.append(row)
        marks = " ".join(f"{v}={'+' if row[v]['richtig'] else '-'}{'*' if row[v]['gefragt'] else ''}" for v in VARIANTS)
        print(f"{entry['anfrage']:34s} {marks}", flush=True)
ZimRegistry.resolve_topic = TODAY  # type: ignore[method-assign]

summary: dict[str, Any] = {}
for variant in VARIANTS:
    every = [row[variant] for rows in results.values() for row in rows]
    summary[variant] = {
        "richtig": sum(o["richtig"] for o in every),
        "von": len(every),
        "je_datei": {name: sum(r[variant]["richtig"] for r in rows) for name, rows in results.items()},
        "gefragt": sum(o["gefragt"] for o in every),
        "tokens": sum(o["tokens"] for o in every),
    }
for variant in ("A", "B"):
    every = [row for rows in results.values() for row in rows]
    summary[variant]["behoben"] = [
        r["anfrage"] for r in every if r[variant]["richtig"] and not r["balanced"]["richtig"]
    ]
    summary[variant]["zerstoert"] = [
        r["anfrage"] for r in every if not r[variant]["richtig"] and r["balanced"]["richtig"]
    ]
    summary[variant]["mehr_gefragt"] = sum(r[variant]["gefragt"] and not r["balanced"]["gefragt"] for r in every)
# a sure resolution never went to the model before M35, so its first call is a new prompt; unsure ones may be cached
fresh = [
    row[v]
    for rows in results.values()
    for row in rows
    for v in ("A", "B")
    if row[v]["neu_gefragt"] and not row["balanced"]["gefragt"]
]
summary["sekunden_je_neuer_frage"] = sorted(o["sekunden"] for o in fresh)
summary["tokens_je_neuer_frage"] = sorted(o["tokens"] for o in fresh)
summary["trocken"] = DRY
for variant in VARIANTS:
    print(variant, json.dumps({k: v for k, v in summary[variant].items() if k != "je_datei"}, ensure_ascii=False))
out_path.write_text(
    json.dumps({"zusammenfassung": summary, "ergebnisse": results}, ensure_ascii=False, indent=1), "utf-8"
)
