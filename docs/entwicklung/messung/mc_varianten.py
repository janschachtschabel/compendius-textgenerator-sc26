"""Matching variants on fixed corpora (project venv): template descriptions and strategies against the gold standard.

Every gold topic is prepared once through CompendiumService.prepare (archives of the server, Model2Vec on). Each
variant replaces the template of the prepared topic and runs CompendiumService.match on the full pool and on the
gold pool. A variant template must keep the search queries and heading patterns of sc26, so the corpus and the
chunks stay the same and every variant is measured on identical paragraphs. Metrics as in mc_final_tables.py:
macro- and micro-F1 of the classification, "richtig unter Top 2" and filled blocks of the selection.

Variants are given as label=template.json:strategy; "-" as template keeps sc26. With --llm the service gets the LLM
of the b-api (gpt-5.6-luna, key from B_API_KEY) for strategy llm; --llm-pool gold limits llm runs to the gold pool.

Usage: python mc_varianten.py <out.json> [--llm] [--llm-pool gold] <label=template:strategy>...
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

ARGS = sys.argv[1:]
USE_LLM = "--llm" in ARGS
LLM_POOL = ARGS[ARGS.index("--llm-pool") + 1] if "--llm-pool" in ARGS else "gold"
if USE_LLM:
    os.environ["LLM_ENABLED"] = "true"
    os.environ["LLM_MAX_CONCURRENCY"] = "4"
    os.environ["LLM_MAX_TOKENS_PER_REQUEST"] = "400000"
    os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
else:
    os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.matching.eval import aggregate, align, evaluate, predictions_from_classification  # noqa: E402
from app.matching.gold import load_gold  # noqa: E402
from app.templates.schema import Template  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD_DIR = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\gold")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000

out_path = Path(ARGS[0])
specs = [a for a in ARGS[1:] if "=" in a]
service = cli_service(ZIMS)
service.settings.model2vec_path = M2V
base = service.templates.get("sc26")
variants: list[tuple[str, Template, str]] = []
for spec in specs:
    label, rest = spec.split("=", 1)
    template_path, strategy = rest.rsplit(":", 1)
    template = base if template_path == "-" else Template.model_validate_json(Path(template_path).read_text("utf-8"))
    if [s.search_queries for s in template.slots] != [s.search_queries for s in base.slots]:
        raise SystemExit(f"{label}: the search queries differ from sc26, the corpus would change")
    if [s.heading_patterns for s in template.slots] != [s.heading_patterns for s in base.slots]:
        raise SystemExit(f"{label}: the heading patterns differ from sc26, the chunks would change")
    variants.append((label, template, strategy))


def selection_stats(selection: dict[str, list], gold: dict, slot_keys: list[str]) -> tuple[int, int, int]:
    judged = correct = covered = 0
    for slot in slot_keys:
        items = selection.get(slot, [])[:2]
        if not items:
            continue
        covered += 1
        for chunk_id, _ in items:
            if chunk_id in gold:
                judged += 1
                correct += gold[chunk_id] == slot
    return judged, correct, covered


rows: dict[tuple[str, str], dict] = {}
tokens = 0
for path in sorted(GOLD_DIR.glob("*.jsonl")):
    gold = load_gold(path)
    prepared = service.prepare(GenerateRequest(topic=gold.topic, parts=["world"]))
    alignment = align(gold, prepared.chunks)
    pools = {"full": prepared, "gold": replace(prepared, chunks=[c for c in prepared.chunks if c.chunk_id in alignment.gold_by_chunk])}
    for label, template, strategy in variants:
        key_of = {slot.id: slot.slot for slot in template.slots}
        slot_keys = [slot.slot for slot in template.content_slots()]
        for pool_name, pool in pools.items():
            if strategy == "llm" and pool_name != LLM_POOL and LLM_POOL != "both":
                continue
            started = time.perf_counter()
            matched = service.match(replace(pool, template=template), strategy, TARGET_LENGTH)
            seconds = time.perf_counter() - started
            if matched.llm is not None:
                tokens += matched.llm.total_tokens
            classified = predictions_from_classification(matched.assignment.classified, template)
            selection = {
                key_of[slot_id]: [[item.chunk.chunk_id, item.score] for item in sorted(items, key=lambda i: -i.score)]
                for slot_id, items in matched.assignment.assigned.items()
                if items
            }
            row = rows.setdefault((label, pool_name), {"eval": [], "judged": 0, "correct": 0, "covered": 0, "n": 0,
                                                        "seconds": 0.0, "tokens": 0, "fallback": 0, "topics": {}})
            row["eval"].append(evaluate(gold.topic, alignment.gold_by_chunk, classified, slot_keys, matcher=label))
            judged, correct, covered = selection_stats(selection, alignment.gold_by_chunk, slot_keys)
            row["judged"] += judged
            row["correct"] += correct
            row["covered"] += covered
            row["n"] += 1
            row["seconds"] += seconds
            if matched.llm is not None:
                row["tokens"] += matched.llm.total_tokens
                row["fallback"] += matched.llm.fallback
            row["topics"][gold.topic] = {"classified": classified, "selection": selection}
    print(f"{gold.topic:26s} fertig, Tokens bisher {tokens}", flush=True)

result = {}
print(f"\n{'Variante':44s} {'Pool':5s} {'macro':>6s} {'micro':>6s} {'falsch':>11s} {'Top 2':>6s} {'belegt':>6s} {'s/Thema':>8s} {'Tokens':>8s}")
for (label, pool_name), row in rows.items():
    total = aggregate(row["eval"])
    top2 = row["correct"] / max(row["judged"], 1)
    result[f"{label}|{pool_name}"] = {
        "macro_f1": total.macro_f1, "micro_f1": total.micro_f1, "assigned": total.assigned,
        "misassigned": total.misassigned, "top2": top2, "covered": row["covered"] / row["n"],
        "seconds_per_topic": row["seconds"] / row["n"], "tokens": row["tokens"], "fallback": row["fallback"],
        "per_slot": {m.slot: {"f1": m.f1, "support": m.support, "predicted": m.predicted} for m in total.slots},
        "topics": row["topics"],
    }
    print(f"{label:44s} {pool_name:5s} {total.macro_f1:6.3f} {total.micro_f1:6.3f} "
          f"{total.misassigned:4d} von {total.assigned:4d} {100 * top2:5.1f}% {row['covered'] / row['n']:6.1f} "
          f"{row['seconds'] / row['n']:8.2f} {row['tokens']:8d}")
out_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
print("Tokens gesamt", tokens)
