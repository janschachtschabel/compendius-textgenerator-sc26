"""Links and the LLM as filters for the side articles of a corpus (M25), on the 20 normal topics of the term gold.

M24 found on the corpora of real materials that side articles without a link to or from the main article were mostly
unfit, and that most unfit side articles are linked sub-articles, which the hit check of article_choice=llm never
sees (it may drop full-text hits only). This measures both on the gold of M8/M10: for the 20 normal topics of
eval/artikelwahl/hauptartikel.yaml the service builds its corpus as for a compendium; every side article of the main
article's archive gets its blind label from eval/artikelwahl/korpus_labels.yaml (2 belongs to the topic, 1 related,
0 does not fit, none when M8 did not label it) and whether it and the main article link to one another (LinkedTo).

With --llm the model rates every article of the corpus in one call per topic, with the service's own hit check
(rate_articles), once for the whole corpus and once for the corpus without the unlinked full-text hits. With --m2v
<model directory> the standard strategy (hybrid_light with Model2Vec, 12,000 characters) matches five corpora per
topic and the printed paragraphs are counted by the label of their article:

- heute: the corpus as the service builds it (llm-free)
- ohne unverlinkte Treffer: without the full-text hits that have no link to or from the main article
- LLM Treffer: without the full-text hits the model rated 0 (balanced today)
- LLM Treffer und verlinkte: without the full-text hits and linked sub-articles the model rated 0
- beides: without the unlinked full-text hits, then without the hits and linked sub-articles rated 0 by the call on
  that smaller corpus

The output holds titles, labels, notes and counts only. The run of ergebnisse/m25_korpus_verlinkung.json (2026-09-25,
gpt-6-luna) measured the corpus before the service left the unlinked full-text hits out itself (sc26 at a97dfd4 with
rate_articles): since then its corpus is the variant "ohne unverlinkte Treffer", and balanced does "beides".

Usage (project venv, from the project root; --llm needs B_API_KEY in .env, the key is never printed):
python docs/entwicklung/messung/mc_korpus_verlinkung.py <out.json> [--llm] [--m2v <model directory>]
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

WITH_LLM = "--llm" in sys.argv
if WITH_LLM:
    os.environ["LLM_ENABLED"] = "true"
else:
    os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.knowledge.article_choice import ArticleChoiceJob, HitCheckReport, rate_articles  # noqa: E402
from app.sources.zim.registry import LinkedTo  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
EVAL = Path("eval") / "artikelwahl"
TARGET_LENGTH = 12_000
SIDE = ("linked", "search")  # the side articles a filter may drop; primary and twin always stay
VARIANTS = ("heute", "ohne unverlinkte Treffer", "LLM Treffer", "LLM Treffer und verlinkte", "beides")


def side_articles(prepared: Any, labels: dict[str, int]) -> list[dict[str, Any]]:
    """Every side article of the main article's archive: origin, label and whether it links with the main article."""
    primary = next(s for s in prepared.sources if s.is_primary)
    archive = next(a for a in service.registry.archives if a.project == primary.project)
    linked_to = LinkedTo(archive, primary)
    rows = []
    for source in prepared.sources:
        if source.origin not in SIDE or source.project != primary.project:
            continue
        started = time.perf_counter()
        linked = linked_to(source)
        rows.append(
            {
                "source_id": source.source_id,
                "titel": source.title,
                "herkunft": source.origin,
                "note": labels.get(f"{source.project}:{source.title}"),
                "verlinkt": linked,
                "ms_verlinkung": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    return rows


def rated(topic: str, sources: list[Any]) -> tuple[dict[str, int | None], int]:
    """The notes of the service's hit check for every article, and the tokens of the call."""
    assert service.llm is not None
    report = HitCheckReport()
    job = ArticleChoiceJob(service.llm.client, service.llm.open_budget())
    notes = rate_articles(job, topic, sources, report)
    if notes is None:
        raise SystemExit(f"{topic}: keine verwertbare Antwort ({report.fallback})")
    return notes, report.total_tokens


def dropped_by(variant: str, rows: list[dict[str, Any]], row: dict[str, Any]) -> set[str]:
    """The source ids a variant drops."""
    unlinked = {r["source_id"] for r in rows if r["herkunft"] == "search" and not r["verlinkt"]}
    whole, smaller = row.get("llm_ganz", {}), row.get("llm_ohne_unverlinkte", {})
    if variant == "heute":
        return set()
    if variant == "ohne unverlinkte Treffer":
        return unlinked
    if variant == "LLM Treffer":
        return {r["source_id"] for r in rows if r["herkunft"] == "search" and whole.get(r["source_id"]) == 0}
    if variant == "LLM Treffer und verlinkte":
        return {r["source_id"] for r in rows if whole.get(r["source_id"]) == 0}
    return unlinked | {r["source_id"] for r in rows if smaller.get(r["source_id"]) == 0}


def printed(prepared: Any, gone: set[str], labels: dict[str, int]) -> tuple[Counter[str], int]:
    """Printed paragraphs by the label of their article, and the filled content blocks, without ``gone``."""
    sources, chunks = prepared.sources, prepared.chunks
    by_id = {source.source_id: source for source in sources}
    prepared.sources = [s for s in sources if s.source_id not in gone]
    prepared.chunks = [c for c in chunks if c.source_id not in gone]
    try:
        matched = service.match(prepared, "hybrid_light", TARGET_LENGTH)
    finally:
        prepared.sources, prepared.chunks = sources, chunks
    counts: Counter[str] = Counter()
    for items in matched.assignment.assigned.values():
        for item in items:
            source = by_id[item.chunk.source_id]
            counts[str(labels.get(f"{source.project}:{source.title}"))] += 1
    content = {slot.id for slot in prepared.template.content_slots()}
    filled = sum(1 for slot_id, items in matched.assignment.assigned.items() if slot_id in content and items)
    return counts, filled


out_path = Path(sys.argv[1])
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
m2v = sys.argv[sys.argv.index("--m2v") + 1] if "--m2v" in sys.argv else None
service = cli_service(ZIMS)
if m2v:
    service.settings.model2vec_path = m2v
gold = yaml.safe_load((EVAL / "korpus_labels.yaml").read_text(encoding="utf-8"))["labels"]
entries = yaml.safe_load((EVAL / "hauptartikel.yaml").read_text(encoding="utf-8"))["anfragen"]
topics = [entry["anfrage"] for entry in entries if entry["art"] == "normal"]

result: dict[str, Any] = {}
for topic in topics:
    labels = gold.get(topic, {})
    prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    rows = side_articles(prepared, labels)
    row: dict[str, Any] = {"hauptartikel": prepared.resolution.title, "artikel": rows}
    if WITH_LLM:
        title = prepared.resolution.title or topic
        row["llm_ganz"], row["tokens_ganz"] = rated(title, prepared.sources)
        unlinked = {r["source_id"] for r in rows if r["herkunft"] == "search" and not r["verlinkt"]}
        if unlinked:
            smaller = [s for s in prepared.sources if s.source_id not in unlinked]
            row["llm_ohne_unverlinkte"], row["tokens_ohne_unverlinkte"] = rated(title, smaller)
        else:
            row["llm_ohne_unverlinkte"], row["tokens_ohne_unverlinkte"] = row["llm_ganz"], 0
    if m2v:
        row["gedruckt"] = {}
        for variant in VARIANTS if WITH_LLM else VARIANTS[:2]:
            counts, filled = printed(prepared, dropped_by(variant, rows, row), labels)
            row["gedruckt"][variant] = {"nach_note": dict(counts), "bausteine": filled}
    result[topic] = row
    states = " ".join(f"{r['herkunft'][0]}{r['note']}{'+' if r['verlinkt'] else '-'}" for r in rows)
    print(f"{topic:25} {states}", flush=True)

out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{len(result)} Themen nach {out_path}")
