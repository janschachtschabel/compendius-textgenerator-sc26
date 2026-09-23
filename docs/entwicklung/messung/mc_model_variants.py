"""Step 2 (project venv): the test app's models as rankers inside the service's own path, on the gold standard.

Each model's pair scores (mc_model_scores.py) become a ranker like BM25 or Model2Vec: divided by the global maximum,
top 15 per block (app/matching/lexical.py normalise_candidates). Then the service's path: fuse_rankings ->
smooth_sections -> assign with budgets for 12,000 characters. "Cross-Encoder sortiert um" keeps the candidates of
hybrid_light + Model2Vec and replaces their fused score by the cross-encoder score (classic re-ranking).

Usage: python mc_model_variants.py <export.json> <out.json> <scores_minilm.json> <scores_cross_encoder.json> <scores_qa.json>
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import ScoredChunk  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.matching.embeddings import Model2VecMatcher  # noqa: E402
from app.matching.eval import predictions_from_classification  # noqa: E402
from app.matching.fusion import fuse_rankings, smooth_sections  # noqa: E402
from app.matching.lexical import BM25Matcher, CharTfidfMatcher, normalise_candidates  # noqa: E402
from app.matching.policy import assign  # noqa: E402
from app.service import _scale_budgets  # noqa: E402

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000
src, out = Path(sys.argv[1]), Path(sys.argv[2])
scores = {name: json.load(open(path, encoding="utf-8"))["topics"]
          for name, path in zip(("minilm", "cross_encoder", "qa"), sys.argv[3:6], strict=True)}

export = json.load(open(src, encoding="utf-8"))
service = cli_service(ZIMS)
bm25, char, m2v = BM25Matcher(), CharTfidfMatcher(), Model2VecMatcher(M2V)
assert m2v.available


class Precomputed:
    """A ranker whose scores were computed elsewhere; treated like the service's own rankers."""

    weight = 1.0

    def __init__(self, name: str, topic: str) -> None:
        self.name = name
        self.table = scores[name][topic]["scores"]

    def score(self, slots, chunks):  # type: ignore[no-untyped-def]
        raw = {s.id: [] for s in slots}
        for slot in slots:
            per_chunk = self.table.get(slot.slot)
            if per_chunk is None:
                continue
            for chunk in chunks:
                value = per_chunk.get(chunk.chunk_id, 0.0)
                if value > 0:
                    raw[slot.id].append((value, chunk, f"{self.name}: {value:.3f}"))
        return normalise_candidates(raw, self.name)


def finish(prepared, chunks, fused):  # type: ignore[no-untyped-def]
    for slot in prepared.template.slots:
        fused.setdefault(slot.id, [])
    fused = smooth_sections(fused, chunks, service.settings.policy_section_smoothing)
    return assign(_scale_budgets(prepared.template, TARGET_LENGTH), chunks, fused, prepared.sources_by_id,
                  confident_score=service.settings.policy_confident_score)


def rerank(fused, ce_by_slot):  # type: ignore[no-untyped-def]
    """Keep the hybrid candidates, order them by the cross-encoder instead (score = CE / best CE among them)."""
    maximum = max(
        (ce_by_slot[slot_id].get(item.chunk.chunk_id, 0.0) for slot_id, items in fused.items() for item in items),
        default=0.0,
    )
    result = {}
    for slot_id, items in fused.items():
        table = ce_by_slot[slot_id]
        rescored = [
            ScoredChunk(chunk=item.chunk, score=round(table.get(item.chunk.chunk_id, 0.0) / maximum, 4) if maximum else 0.0,
                        matcher="ce_rerank", reasons=item.reasons)
            for item in items
        ]
        result[slot_id] = sorted(rescored, key=lambda s: -s.score)
    return result


for topic in export["topics"]:
    name = topic["topic"]
    prepared = service.prepare(GenerateRequest(topic=name))
    key_of = {slot.id: slot.slot for slot in prepared.template.slots}
    gold_ids = set(topic["gold"])
    pools = {"full": prepared.chunks, "gold": [c for c in prepared.chunks if c.chunk_id in gold_ids]}
    minilm, ce, qa = (Precomputed(n, name) for n in ("minilm", "cross_encoder", "qa"))
    slots = prepared.template.slots
    ce_by_slot = {slot.id: ce.table.get(slot.slot, {}) for slot in slots}
    for pool_name, chunks in pools.items():
        pool = replace(prepared, chunks=chunks)
        hybrid = fuse_rankings([r.score(slots, chunks) for r in (bm25, char, m2v)], [bm25.weight, char.weight, m2v.weight])
        variants = {
            "MiniLM-Satzvektoren allein": fuse_rankings([minilm.score(slots, chunks)], [1.0]),
            "Cross-Encoder allein": fuse_rankings([ce.score(slots, chunks)], [1.0]),
            "Frage-Antwort-Modell allein": fuse_rankings([qa.score(slots, chunks)], [1.0]),
            "hybrid_light + M2V, Cross-Encoder sortiert um": rerank(hybrid, ce_by_slot),
        }
        variants["hybrid_light + M2V + Cross-Encoder (fusioniert)"] = fuse_rankings(
            [r.score(slots, chunks) for r in (bm25, char, m2v)] + [ce.score(slots, chunks)],
            [bm25.weight, char.weight, m2v.weight, 1.0])
        # the re-ranking scores only the hybrid candidates: record how many (block, paragraph) pairs that is
        rerank_pairs = sum(len(items) for items in hybrid.values())
        # distinct paragraphs the rankers propose at all: what an LLM would have to judge if it only saw candidates
        candidate_chunks = len({item.chunk.chunk_id for items in hybrid.values() for item in items})
        for label, fused in variants.items():
            assignment = finish(pool, chunks, fused)
            topic["mine"][pool_name][label] = {
                "ms": 0,
                "candidate_pairs": rerank_pairs if "sortiert um" in label else None,
                "candidate_chunks": candidate_chunks if "sortiert um" in label else None,
                "pool_chunks": len(chunks),
                "classified": predictions_from_classification(assignment.classified, prepared.template),
                "selection": {
                    key_of[slot_id]: [[sc.chunk.chunk_id, sc.score] for sc in sorted(items, key=lambda s: -s.score)]
                    for slot_id, items in assignment.assigned.items()
                    if items
                },
            }
    print("done", name, flush=True)

out.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
print("written", out)
