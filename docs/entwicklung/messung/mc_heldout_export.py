"""Held-out topics (project venv): chunks and the selections of the project's strategies, no gold labels.

Same variants and budget as mc_export.py, one candidate pool (the full corpus). The output has the shape of the
gold export, so the judge reads it unchanged.

Usage: python mc_heldout_export.py <out.json> <topic,topic,...>
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.matching.eval import predictions_from_classification  # noqa: E402

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
M2V = "JanSchachtschabel/m2v-gte-256-edu"
OUT = Path(sys.argv[1])
TOPICS = sys.argv[2].split(",")
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
for name in TOPICS:
    prepared = service.prepare(GenerateRequest(topic=name))
    sources = prepared.sources_by_id
    template = prepared.template
    topic: dict[str, object] = {
        "topic": name,
        "title": prepared.resolution.title,
        "slots": [slot.model_dump() for slot in template.slots],
        "gold": {},
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
    for label, strategy, model_path in runs:
        service.settings.model2vec_path = model_path
        service.match(prepared, strategy, TARGET_LENGTH)  # warm-up: model load, caches
        started = time.perf_counter()
        matched = service.match(prepared, strategy, TARGET_LENGTH)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        topic["mine"].setdefault("full", {})[label] = {  # type: ignore[index]
            "ms": elapsed_ms,
            "classified": predictions_from_classification(matched.assignment.classified, template),
            "selection": {
                key_of[slot_id]: [[sc.chunk.chunk_id, sc.score] for sc in sorted(items, key=lambda s: -s.score)]
                for slot_id, items in matched.assignment.assigned.items()
                if items
            },
        }
    export["topics"].append(topic)  # type: ignore[union-attr]
    print(f"{name:26s} resolved={prepared.resolution.title!r} chunks={len(prepared.chunks):4d}", flush=True)

OUT.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
print("written", OUT, OUT.stat().st_size // 1024, "KB")
