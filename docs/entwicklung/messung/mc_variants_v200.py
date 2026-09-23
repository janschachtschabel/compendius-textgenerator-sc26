"""Ranker variants through the service's own path (project venv, code state 2.0.0).

Same steps as CompendiumService.match: component rankings -> fuse_rankings -> smooth_sections -> assign with budgets
scaled to the target length. The variant "BM25 + Char + M2V" is hybrid_light itself and must reproduce the
selection the export already holds for "hybrid_light + M2V" - that check runs first and stops the script on a
mismatch. Adds the variants to topic["mine"] of the given export.

Usage: python mc_variants_v200.py <export.json> <out.json>
"""

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
from app.matching.embeddings import Model2VecMatcher  # noqa: E402
from app.matching.eval import predictions_from_classification  # noqa: E402
from app.matching.fusion import fuse_rankings, smooth_sections  # noqa: E402
from app.matching.lexical import BM25Matcher, CharTfidfMatcher  # noqa: E402
from app.matching.policy import assign  # noqa: E402
from app.service import _scale_budgets  # noqa: E402

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000
src, out = Path(sys.argv[1]), Path(sys.argv[2])

export = json.load(open(src, encoding="utf-8"))
service = cli_service(ZIMS)
bm25, char, m2v = BM25Matcher(), CharTfidfMatcher(), Model2VecMatcher(M2V)
assert m2v.available, "Model2Vec model not available offline"
CHECK = "BM25 + Char + M2V (Nachbau hybrid_light)"
VARIANTS = {
    CHECK: [bm25, char, m2v],
    "Model2Vec allein": [m2v],
    "BM25 + Model2Vec": [bm25, m2v],
}


def run(prepared, chunks, components):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    rankings = [component.score(prepared.template.slots, chunks) for component in components]
    fused = fuse_rankings(rankings, [component.weight for component in components])
    for slot in prepared.template.slots:
        fused.setdefault(slot.id, [])
    fused = smooth_sections(fused, chunks, service.settings.policy_section_smoothing)
    sources = prepared.sources_by_id
    assignment = assign(
        _scale_budgets(prepared.template, TARGET_LENGTH), chunks, fused, sources,
        confident_score=service.settings.policy_confident_score,
    )
    return assignment, int((time.perf_counter() - started) * 1000)


for topic in export["topics"]:
    prepared = service.prepare(GenerateRequest(topic=topic["topic"]))
    gold_ids = set(topic["gold"])
    pools = {"full": prepared.chunks}
    if gold_ids:
        pools["gold"] = [c for c in prepared.chunks if c.chunk_id in gold_ids]
    key_of = {slot.id: slot.slot for slot in prepared.template.slots}
    for pool_name, chunks in pools.items():
        pool = replace(prepared, chunks=chunks)
        for label, components in VARIANTS.items():
            run(pool, chunks, components)  # warm-up, as in mc_export.py
            assignment, elapsed_ms = run(pool, chunks, components)
            entry = {
                "ms": elapsed_ms,
                "classified": predictions_from_classification(assignment.classified, prepared.template),
                "selection": {
                    key_of[slot_id]: [[sc.chunk.chunk_id, sc.score] for sc in sorted(items, key=lambda s: -s.score)]
                    for slot_id, items in assignment.assigned.items()
                    if items
                },
            }
            if label == CHECK:
                reference = topic["mine"][pool_name]["hybrid_light + M2V"]
                same = entry["classified"] == reference["classified"] and entry["selection"] == reference["selection"]
                if not same:
                    sys.exit(f"MISMATCH {topic['topic']} {pool_name}: the rebuild differs from hybrid_light + M2V")
                continue
            topic["mine"][pool_name][label] = entry
    print("done", topic["topic"], "- rebuild of hybrid_light identical", flush=True)

out.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
print("written", out)
