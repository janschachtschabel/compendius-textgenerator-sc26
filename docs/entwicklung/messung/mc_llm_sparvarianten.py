"""Cheaper ways of matcher=llm on the gold pool (project venv, b-api, the model of B_API_MODEL).

Every gold topic is prepared once through CompendiumService.prepare (archives of the server, Model2Vec on); the pool
is the paragraphs the gold labels, as in mc_varianten.py. Four ways, all through CompendiumService.match:

- rules: hybrid_light, the default strategy;
- llm: matcher=llm as the service runs it, with the module constants of the code on PYTHONPATH (until D36 25
  paragraphs per call of 700 characters each, since D36 50 of 400);
- llm_billig and llm_50x400: 50 paragraphs per call and 400 characters each; llm_25x700: 25 and 700 (the module
  constants, patched for the run);
- llm_zweifel: only the paragraphs the policy decides without a confident signal go to the model - the ones it sends
  to the default block or leaves out as off-topic; a confident paragraph (the lead of an article, a heading of the
  lexicon, a score from POLICY_CONFIDENT_SCORE on) keeps the policy's block.

Metrics as in mc_varianten.py: macro- and micro-F1 of the classification, misassigned paragraphs, tokens, seconds per
topic. The b-api answers a prompt it has seen from its cache; --rotieren starts every pool in the middle, so the model
gets the same paragraphs in other batches - an independent sample of the same setting (D36, second run).

Usage: python mc_llm_sparvarianten.py <out.json> [--rotieren] <way>...
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ["LLM_MAX_CONCURRENCY"] = "4"
os.environ["LLM_MAX_TOKENS_PER_REQUEST"] = "400000"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import app.matching.llm_assignment as llm_assignment  # noqa: E402
import app.service as service_module  # noqa: E402
from app.cli_common import cli_service  # noqa: E402
from app.domain.models import Chunk, Source  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.matching.eval import aggregate, align, evaluate, predictions_from_classification  # noqa: E402
from app.matching.gold import load_gold  # noqa: E402
from app.matching.policy import LEXICON_SCORE, AssignmentResult  # noqa: E402
from app.templates.schema import Template  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD_DIR = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\gold")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000

out_path = Path(sys.argv[1])
ways = [arg for arg in sys.argv[2:] if not arg.startswith("--")]
ROTATE = "--rotieren" in sys.argv[2:]
service = cli_service(ZIMS)
service.settings.model2vec_path = M2V
assert service.llm is not None, "LLM_ENABLED did not reach the settings"
original_assign = llm_assignment.assign_with_llm
original_combine = llm_assignment._combine
DEFAULTS = (llm_assignment.BATCH_SIZE, llm_assignment.TEXT_CHARS)
doubt_counts = {"angeboten": 0, "alle": 0}


def sure(chunk: Chunk, rule_based: AssignmentResult, confident_score: float) -> bool:
    """The policy's own test for a confident decision (app/matching/policy.py, assign)."""
    best = max((scores.get(chunk.chunk_id, 0.0) for scores in rule_based.slot_scores.values()), default=0.0)
    lexicon = chunk.lexicon_slot is not None and best >= LEXICON_SCORE
    return chunk.is_lead or lexicon or best >= confident_score


def doubt_band(
    template: Template,
    chunks: Sequence[Chunk],
    sources: dict[str, Source],
    rule_based: AssignmentResult,
    job: llm_assignment.AssignmentJob,
) -> tuple[AssignmentResult, llm_assignment.LlmAssignmentReport]:
    """matcher=llm for the doubtful paragraphs only; the rest keep the policy's decision in the combination."""
    generated = {slot.slot for slot in template.slots if slot.is_generated}
    offered_all = [c for c in chunks if c.lexicon_slot not in generated]
    doubtful = [c for c in offered_all if not sure(c, rule_based, service.settings.policy_confident_score)]
    doubt_counts["angeboten"] += len(doubtful)
    doubt_counts["alle"] += len(offered_all)

    def combine_all(template_, offered, decided, rule_based_, skipped):  # type: ignore[no-untyped-def]
        return original_combine(template_, offered_all, decided, rule_based_, skipped=len(chunks) - len(offered_all))

    llm_assignment._combine = combine_all
    try:
        return original_assign(template, doubtful, sources, rule_based, job)
    finally:
        llm_assignment._combine = original_combine


def configure(way: str) -> str:
    """Patch the module for the way; returns the strategy name to pass to CompendiumService.match."""
    llm_assignment.BATCH_SIZE, llm_assignment.TEXT_CHARS = DEFAULTS
    service_module.assign_with_llm = original_assign
    if way == "rules":
        return "hybrid_light"
    if way in ("llm_billig", "llm_50x400"):
        llm_assignment.BATCH_SIZE, llm_assignment.TEXT_CHARS = 50, 400
    elif way == "llm_25x700":
        llm_assignment.BATCH_SIZE, llm_assignment.TEXT_CHARS = 25, 700
    elif way == "llm_zweifel":
        service_module.assign_with_llm = doubt_band
    elif way != "llm":
        raise SystemExit(f"unknown way {way}")
    return "llm"


prepared_topics = []
for path in sorted(GOLD_DIR.glob("*.jsonl")):
    gold = load_gold(path)
    prepared = service.prepare(GenerateRequest(topic=gold.topic, parts=["world"]))
    alignment = align(gold, prepared.chunks)
    chunks = [c for c in prepared.chunks if c.chunk_id in alignment.gold_by_chunk]
    if ROTATE:
        chunks = chunks[len(chunks) // 2 :] + chunks[: len(chunks) // 2]
    pool = replace(prepared, chunks=chunks)
    prepared_topics.append((gold, alignment, pool))

result: dict[str, dict] = {}
for way in ways:
    strategy = configure(way)
    evals, tokens, seconds, fallback, paragraphs, per_topic = [], 0, 0.0, 0, 0, {}
    for gold, alignment, pool in prepared_topics:
        template = pool.template
        slot_keys = [slot.slot for slot in template.content_slots()]
        started = time.perf_counter()
        matched = service.match(pool, strategy, TARGET_LENGTH)
        spent = time.perf_counter() - started
        seconds += spent
        per_topic[gold.topic] = round(spent, 2)
        if matched.llm is not None:
            tokens += matched.llm.total_tokens
            fallback += matched.llm.fallback
            paragraphs += matched.llm.paragraphs
        classified = predictions_from_classification(matched.assignment.classified, template)
        evals.append(evaluate(gold.topic, alignment.gold_by_chunk, classified, slot_keys, matcher=way))
    total = aggregate(evals)
    result[way] = {
        "macro_f1": total.macro_f1, "micro_f1": total.micro_f1, "assigned": total.assigned,
        "misassigned": total.misassigned, "tokens": tokens, "llm_paragraphs": paragraphs, "fallback": fallback,
        "seconds": round(seconds, 1), "seconds_per_topic": per_topic, "rotated": ROTATE,
        "per_slot": {m.slot: {"f1": m.f1, "support": m.support, "predicted": m.predicted} for m in total.slots},
    }
    print(f"{way:12s} macro {total.macro_f1:.3f} micro {total.micro_f1:.3f} falsch {total.misassigned:4d} von "
          f"{total.assigned:4d}  LLM-Absätze {paragraphs:4d}  Rückfall {fallback:3d}  Token {tokens:7d}  {seconds:6.1f} s",
          flush=True)
if "llm_zweifel" in ways:
    print(f"Zweifelsband: {doubt_counts['angeboten']} von {doubt_counts['alle']} Absätzen an das Modell")
out_path.write_text(json.dumps({"wege": result, "zweifelsband": doubt_counts}, ensure_ascii=False, indent=1), "utf-8")
