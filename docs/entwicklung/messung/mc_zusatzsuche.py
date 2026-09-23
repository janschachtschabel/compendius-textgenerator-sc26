"""Wikibooks and Wikiversity through their full-text search (project venv; b-api, gpt-5.6-luna, for the hit check).

The service takes a page from these archives only when its title equals the topic, which gave 2 pages for the 20
normal topics (mc_zusatzquellen.py). Here build_corpus also adds the first full-text hits for the topic from each of
the two archives, as full-text hits like its own per block. Every topic is matched three ways with the standard
strategy (hybrid_light with Model2Vec, 12,000 characters): without the extra hits, with them, and with them after
the hit check of article_choice=llm (app/knowledge/article_choice.py) dropped what it rates 0. The output counts per
way the filled content blocks, the printed paragraphs from Wikibooks and Wikiversity and the blocks they went to,
and lists every extra hit with the check's verdict and its printed paragraphs.

Usage: python mc_zusatzsuche.py <out.json> <hits per archive>
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import yaml

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.knowledge.article_choice import ArticleChoiceJob, check_hits  # noqa: E402
from app.knowledge.related import is_blacklisted  # noqa: E402
from app.sources.zim.registry import ZimRegistry  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ARCHIVES = [
    DATA / "wikipedia_de_all_nopic_2026-01.zim",
    DATA / "klexikon_de_all_maxi_2026-08.zim",
    DATA / "wikibooks_de_all_nopic_2026-01.zim",
    DATA / "wikiversity_de_all_nopic_2026-07.zim",
]
EVAL = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\artikelwahl")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000
EXTRA = {"wikibooks", "wikiversity"}
META = ("wikibooks:", "wikiversity:", "benutzer:", "hilfe:", "vorlage:", "kategorie:", "diskussion:")

out_path, per_archive = Path(sys.argv[1]), int(sys.argv[2])
topics = [e["anfrage"] for e in yaml.safe_load((EVAL / "hauptartikel.yaml").read_text("utf-8"))["anfragen"]
          if e["art"] == "normal"]
service = cli_service([str(p) for p in ARCHIVES])
service.settings.model2vec_path = M2V
assert service.llm is not None, "LLM_ENABLED did not reach the settings"
original_build = ZimRegistry.build_corpus
state = {"extra": True}


def build_with_extra_search(self, resolution, slots, max_articles):  # type: ignore[no-untyped-def]
    sources = original_build(self, resolution, slots, max_articles)
    if not state["extra"] or not sources:
        return sources
    seen = {(s.project, s.title.lower()) for s in sources}
    for archive in self.archives:
        if archive.project not in EXTRA:
            continue
        added = 0
        for title in archive.search(sources[0].title, per_archive * 3):
            if added >= per_archive:
                break
            if title.lower().startswith(META) or is_blacklisted(title):
                continue
            hit = self._read_source(archive, title, seen)
            if hit is not None:
                hit.origin = "search"
                sources.append(hit)
                added += 1
    return sources


ZimRegistry.build_corpus = build_with_extra_search  # type: ignore[method-assign]


def printed(prepared) -> tuple[int, Counter, dict[str, int]]:  # type: ignore[no-untyped-def]
    matched = service.match(prepared, "hybrid_light", TARGET_LENGTH)
    content = {slot.id: slot.title for slot in prepared.template.content_slots()}
    by_id = prepared.sources_by_id
    blocks: Counter = Counter()
    per_source: Counter = Counter()
    for slot_id, items in matched.assignment.assigned.items():
        for item in items:
            source = by_id[item.chunk.source_id]
            if source.project in EXTRA:
                blocks[content.get(slot_id, slot_id)] += 1
                per_source[f"{source.project}:{source.title}"] += 1
    filled = sum(1 for slot_id, items in matched.assignment.assigned.items() if slot_id in content and items)
    return filled, blocks, dict(per_source)


def drop(prepared, gone: set[str]) -> None:  # type: ignore[no-untyped-def]
    prepared.sources = [s for s in prepared.sources if s.source_id not in gone]
    prepared.chunks = [c for c in prepared.chunks if c.source_id not in gone]


result: dict[str, dict] = {}
totals = {"ohne": Counter(), "mit": Counter(), "geprueft": Counter()}
tokens = 0
for topic in topics:
    state["extra"] = False
    base = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    filled_base, _, _ = printed(base)
    state["extra"] = True
    prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    extra_hits = [s for s in prepared.sources if s.project in EXTRA and s.origin == "search"]
    filled_with, blocks_with, per_source_with = printed(prepared)
    job = ArticleChoiceJob(service.llm.client, service.llm.open_budget())
    gone, report = check_hits(job, prepared.resolution.title or topic, prepared.sources)
    tokens += report.total_tokens
    drop(prepared, gone)
    filled_checked, blocks_checked, per_source_checked = printed(prepared)
    dropped = set(report.dropped)
    result[topic] = {
        "bausteine_gefuellt": {"ohne": filled_base, "mit": filled_with, "geprueft": filled_checked},
        "gedruckt_zusatz": {"mit": dict(blocks_with), "geprueft": dict(blocks_checked)},
        "treffer": [
            {
                "projekt": s.project, "titel": s.title, "verworfen": s.title in dropped,
                "gedruckt_mit": per_source_with.get(f"{s.project}:{s.title}", 0),
                "gedruckt_geprueft": per_source_checked.get(f"{s.project}:{s.title}", 0),
            }
            for s in extra_hits
        ],
        "verworfen_sonst": [t for t in dropped if t not in {s.title for s in extra_hits}],
    }
    totals["ohne"]["bausteine"] += filled_base
    totals["mit"]["bausteine"] += filled_with
    totals["geprueft"]["bausteine"] += filled_checked
    totals["mit"]["gedruckt"] += sum(blocks_with.values())
    totals["geprueft"]["gedruckt"] += sum(blocks_checked.values())
    totals["mit"]["treffer"] += len(extra_hits)
    totals["geprueft"]["treffer"] += sum(1 for s in extra_hits if s.title not in dropped)
    marks = ", ".join(
        f"{'x' if s.title in dropped else '+'}{s.project[:5]}:{s.title[:40]}"
        f"({per_source_with.get(f'{s.project}:{s.title}', 0)})"
        for s in extra_hits
    )
    print(f"{topic:24s} Bausteine {filled_base}/{filled_with}/{filled_checked}  {marks}")
print(f"Summe: {dict(totals['ohne'])} | mit Zusatzsuche {dict(totals['mit'])} | nach Prüfung {dict(totals['geprueft'])}"
      f" | Token der Prüfung {tokens}")
out_path.write_text(json.dumps({"tokens": tokens, "themen": result}, ensure_ascii=False, indent=1), "utf-8")
