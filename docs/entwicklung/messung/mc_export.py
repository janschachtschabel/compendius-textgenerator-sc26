"""Step 1 (project venv): export gold-labelled chunks per topic and the predictions of the project's strategies."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.matching.eval import align, predictions_from_classification  # noqa: E402
from app.matching.gold import load_gold  # noqa: E402

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD_DIR = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\gold")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
OUT = Path(sys.argv[1])
TARGET_LENGTH = 12_000

service = cli_service(ZIMS)
runs = [
    ("lexicon_only", "lexicon_only", ""),
    ("bm25", "bm25", ""),
    ("char_tfidf", "char_tfidf", ""),
    ("hybrid_light (ohne M2V)", "hybrid_light", ""),
    ("hybrid_light + M2V", "hybrid_light", M2V),
]

export: dict[str, object] = {"topics": []}
for path in sorted(GOLD_DIR.glob("*.jsonl")):
    gold = load_gold(path)
    prepared = service.prepare(GenerateRequest(topic=gold.topic))
    alignment = align(gold, prepared.chunks)
    sources = prepared.sources_by_id
    template = prepared.template
    topic: dict[str, object] = {
        "topic": gold.topic,
        "title": prepared.resolution.title,
        "stale_labels": len(alignment.stale),
        "slots": [slot.model_dump() for slot in template.slots],
        "gold": alignment.gold_by_chunk,
        "chunks": [
            {
                **chunk.model_dump(mode="json"),
                "full_heading": chunk.full_heading,
                "source_title": sources[chunk.source_id].title,
                "source_project": sources[chunk.source_id].project,
                "source_is_primary": sources[chunk.source_id].is_primary,
                "source_origin": sources[chunk.source_id].origin,
            }
            for chunk in prepared.chunks
        ],
        "mine": {},
    }
    key_of = {slot.id: slot.slot for slot in template.slots}
    pools = {
        "full": prepared,
        "gold": replace(prepared, chunks=[c for c in prepared.chunks if c.chunk_id in alignment.gold_by_chunk]),
    }
    for pool_name, pool in pools.items():
        for label, name, model_path in runs:
            service.settings.model2vec_path = model_path
            service.match(pool, name, TARGET_LENGTH)  # warm-up: model load, caches
            started = time.perf_counter()
            matched = service.match(pool, name, TARGET_LENGTH)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            topic["mine"].setdefault(pool_name, {})[label] = {  # type: ignore[index]
                "ms": elapsed_ms,
                "classified": predictions_from_classification(matched.assignment.classified, template),
                "selection": {
                    key_of[slot_id]: [[sc.chunk.chunk_id, sc.score] for sc in sorted(items, key=lambda s: -s.score)]
                    for slot_id, items in matched.assignment.assigned.items()
                    if items
                },
            }
    export["topics"].append(topic)  # type: ignore[union-attr]
    labelled = sum(1 for v in alignment.gold_by_chunk.values())
    print(f"{gold.topic:26s} chunks={len(prepared.chunks):4d} gold={labelled:4d} stale={len(alignment.stale)}")

OUT.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
print("written", OUT, OUT.stat().st_size // 1024, "KB")
