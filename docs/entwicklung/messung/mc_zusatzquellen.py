"""Wikibooks and Wikiversity as further sources (project venv, no LLM): what they add to the corpus and the text.

For the 20 normal topics of eval/artikelwahl/hauptartikel.yaml the service builds its corpus twice, with Wikipedia and
Klexikon (the standard profile) and with Wikibooks and Wikiversity added (the extended profile), and matches both with
the standard strategy (hybrid_light with Model2Vec, 12,000 characters). The output lists every Wikibooks and
Wikiversity page that enters a corpus - how it came in, its paragraphs, the paragraphs printed and the blocks they
went to - and counts the filled content blocks of both profiles. A pool with the beginning of every such page and
of its printed paragraphs is written separately for the relevance labels and stays outside the repository.

Usage: python mc_zusatzquellen.py <out.json> <pool.json>
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
STANDARD = [DATA / "wikipedia_de_all_nopic_2026-01.zim", DATA / "klexikon_de_all_maxi_2026-08.zim"]
EXTENDED = [*STANDARD, DATA / "wikibooks_de_all_nopic_2026-01.zim", DATA / "wikiversity_de_all_nopic_2026-07.zim"]
EVAL = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\artikelwahl")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000
EXTRA = {"wikibooks", "wikiversity"}

out_path, pool_path = Path(sys.argv[1]), Path(sys.argv[2])
topics = [e["anfrage"] for e in yaml.safe_load((EVAL / "hauptartikel.yaml").read_text("utf-8"))["anfragen"]
          if e["art"] == "normal"]


def run(paths: list[Path]) -> tuple[dict, dict]:
    service = cli_service([str(p) for p in paths])
    service.settings.model2vec_path = M2V
    rows: dict[str, dict] = {}
    pool: dict[str, dict] = {}
    for topic in topics:
        prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
        matched = service.match(prepared, "hybrid_light", TARGET_LENGTH)
        by_id = prepared.sources_by_id
        content = {slot.id: slot.title for slot in prepared.template.content_slots()}
        printed: dict[str, list[str]] = defaultdict(list)
        for slot_id, items in matched.assignment.assigned.items():
            for item in items:
                printed[item.chunk.source_id].append(content.get(slot_id, slot_id))
        chunks = Counter(chunk.source_id for chunk in prepared.chunks)
        extra = []
        for source in prepared.sources:
            if source.project not in EXTRA:
                continue
            extra.append({
                "projekt": source.project, "titel": source.title, "herkunft": source.origin,
                "absaetze": chunks.get(source.source_id, 0), "gedruckt": len(printed.get(source.source_id, [])),
                "bausteine": dict(Counter(printed.get(source.source_id, []))),
            })
            pool.setdefault(topic, {})[f"{source.project}:{source.title}"] = {
                "anfang": " ".join(source.lead_text.split())[:400],
                "gedruckt": [c.text[:300] for c in prepared.chunks if c.source_id == source.source_id
                             and source.source_id in printed][:3],
            }
        filled = sum(1 for slot_id, items in matched.assignment.assigned.items() if slot_id in content and items)
        rows[topic] = {
            "bausteine_gefuellt": filled, "gedruckt": sum(len(v) for v in printed.values()),
            "artikel": len(prepared.sources), "zusatzquellen": extra,
            "verdraengt": [by_id[s].title for s in by_id if by_id[s].project not in EXTRA],
        }
    return rows, pool


standard, _ = run(STANDARD)
extended, pool = run(EXTENDED)
print(f"{'Thema':26s} Bausteine std/ext  gedruckt std/ext  Zusatzquellen (gedruckt)")
for topic in topics:
    s, e = standard[topic], extended[topic]
    extra = ", ".join(f"{x['projekt'][:5]}:{x['titel']} ({x['gedruckt']})" for x in e["zusatzquellen"]) or "-"
    print(f"{topic:26s} {s['bausteine_gefuellt']:3d}/{e['bausteine_gefuellt']:<3d}        "
          f"{s['gedruckt']:3d}/{e['gedruckt']:<3d}          {extra}")
total = Counter()
for topic in topics:
    for x in extended[topic]["zusatzquellen"]:
        total[x["projekt"]] += 1
        total[f"{x['projekt']} gedruckt"] += x["gedruckt"]
print("Summe:", dict(total), "| gefüllte Bausteine std/ext:",
      sum(r["bausteine_gefuellt"] for r in standard.values()), "/", sum(r["bausteine_gefuellt"] for r in extended.values()))
out_path.write_text(json.dumps({"standard": standard, "erweitert": extended}, ensure_ascii=False, indent=1), "utf-8")
pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
