"""What dropping the full-text hits the model rated 0 does to the printed compendium (project venv, no LLM calls).

Reads the ratings mc_treffer_llm.py wrote and builds the corpus of the 20 normal topics twice, as the service does and
without the hits rated 0, matches both with the standard strategy (hybrid_light with Model2Vec, 12,000 characters)
and counts the printed paragraphs by the blind label of their article (eval/artikelwahl/korpus_labels.yaml) and the
filled content blocks.

Usage: python mc_treffer_wirkung.py <ratings.json> <out.json>
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import yaml

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
EVAL = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\artikelwahl")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000

ratings_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
dropped = {(r["thema"], r["titel"]) for r in json.loads(ratings_path.read_text("utf-8"))["treffer"] if r["llm"] == 0}
labels = yaml.safe_load((EVAL / "korpus_labels.yaml").read_text(encoding="utf-8"))["labels"]
entries = yaml.safe_load((EVAL / "hauptartikel.yaml").read_text(encoding="utf-8"))["anfragen"]
topics = [e["anfrage"] for e in entries if e["art"] == "normal"]
service = cli_service(ZIMS)
service.settings.model2vec_path = M2V


def printed_by_label(topic: str, drop: bool) -> tuple[Counter, int, int]:
    prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    if drop:
        gone = {s.source_id for s in prepared.sources if s.origin == "search" and (topic, s.title) in dropped}
        prepared.sources = [s for s in prepared.sources if s.source_id not in gone]
        prepared.chunks = [c for c in prepared.chunks if c.source_id not in gone]
    matched = service.match(prepared, "hybrid_light", TARGET_LENGTH)
    by_id = prepared.sources_by_id
    counts: Counter = Counter()
    for items in matched.assignment.assigned.values():
        for item in items:
            source = by_id[item.chunk.source_id]
            counts[labels.get(topic, {}).get(f"{source.project}:{source.title}")] += 1
    content = {slot.id for slot in prepared.template.content_slots()}
    filled = sum(1 for slot_id, items in matched.assignment.assigned.items() if slot_id in content and items)
    return counts, filled, len(prepared.chunks)


result: dict[str, dict] = {}
totals = {False: Counter(), True: Counter()}
filled_total = {False: 0, True: 0}
for topic in topics:
    row = {}
    for drop in (False, True):
        counts, filled, chunks = printed_by_label(topic, drop)
        totals[drop].update(counts)
        filled_total[drop] += filled
        row["ohne_0_treffer" if drop else "heute"] = {
            "gedruckt": {str(k): v for k, v in counts.items()}, "bausteine_gefuellt": filled, "absaetze": chunks,
        }
    result[topic] = row
for drop in (False, True):
    c = totals[drop]
    name = "ohne 0-Treffer" if drop else "heute"
    print(f"{name:15s} gedruckt 2/1/0/ohne Note: {c[2]}/{c[1]}/{c[0]}/{c[None]} von {sum(c.values())}, "
          f"gefüllte Inhaltsbausteine: {filled_total[drop]}")
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
