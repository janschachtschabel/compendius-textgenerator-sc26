"""matcher=llm through the service itself (project venv, gpt-5.6-luna via b-api), measured like M5 on the gold pool.

For every gold topic the service prepares the corpus (CompendiumService.prepare), the chunks are cut to the
labelled paragraphs (the gold pool of M4 and M5) and CompendiumService.match runs with matcher=llm: the default
strategy (hybrid_light with Model2Vec) first, the model on top (app/matching/llm_assignment.py). The service's own
LLM settings apply, with four calls at a time as in M5; the key comes from B_API_KEY. A hard token limit stops the
run before the agreed budget. The result is evaluated with app.matching.eval like every other method and compared
paragraph by paragraph with the answers of the first run (m5_llm_zuordnung.json).

Usage: python mc_llm_dienst.py <m5_llm_zuordnung.json> <out.json> <token_limit>
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ["LLM_MAX_CONCURRENCY"] = "4"
os.environ["LLM_MAX_TOKENS_PER_REQUEST"] = "100000"  # one topic of the gold pool, well below it
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.matching.eval import aggregate, align, evaluate, predictions_from_classification  # noqa: E402
from app.matching.gold import load_gold  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD_DIR = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\gold")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000

first_run, out_path, token_limit = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
earlier = {topic: data["answers"] for topic, data in json.loads(first_run.read_text(encoding="utf-8"))["topics"].items()}
service = cli_service(ZIMS)
service.settings.model2vec_path = M2V
assert service.llm is not None, "LLM_ENABLED and B_API_KEY are needed"
assert service.llm_unavailable() is None, service.llm_unavailable()

topics: dict[str, dict] = {}
evaluations = []
judged = correct = 0
same = compared = 0
spent = 0
for path in sorted(GOLD_DIR.glob("*.jsonl")):
    if spent >= token_limit:
        print(f"gestoppt an der Tokengrenze {token_limit}")
        break
    gold = load_gold(path)
    prepared = service.prepare(GenerateRequest(topic=gold.topic, parts=["world"]))
    alignment = align(gold, prepared.chunks)
    pool = replace(prepared, chunks=[c for c in prepared.chunks if c.chunk_id in alignment.gold_by_chunk])
    started = time.perf_counter()
    matched = service.match(pool, "llm", TARGET_LENGTH)
    wall = time.perf_counter() - started
    report = matched.llm
    assert report is not None
    spent += report.total_tokens

    template = prepared.template
    key_of = {slot.id: slot.slot for slot in template.slots}
    slot_keys = [slot.slot for slot in template.content_slots()]
    classified = predictions_from_classification(matched.assignment.classified, template)
    evaluations.append(evaluate(gold.topic, alignment.gold_by_chunk, classified, slot_keys, matcher="llm"))
    selection = {
        key_of[slot_id]: [[item.chunk.chunk_id, item.score] for item in sorted(items, key=lambda i: -i.score)]
        for slot_id, items in matched.assignment.assigned.items()
        if items
    }
    for key in slot_keys:  # "richtig unter Top 2" as in mc_final_tables.py
        for chunk_id, _ in selection.get(key, [])[:2]:
            if chunk_id in alignment.gold_by_chunk:
                judged += 1
                correct += alignment.gold_by_chunk[chunk_id] == key
    if report.fallback == 0:  # every decision is the model's: compare it with the first run
        for chunk in pool.chunks:
            answer = earlier.get(gold.topic, {}).get(chunk.chunk_id)
            if answer is None:
                continue
            compared += 1
            same += answer[0] == classified.get(chunk.chunk_id, "keiner")
    topics[gold.topic] = {
        "paragraphs": report.paragraphs, "answered": report.answered, "fallback": report.fallback,
        "fallbacks": report.fallbacks, "unknown_keys": report.unknown_keys, "calls": report.calls,
        "tokens": report.total_tokens, "wall_seconds": round(wall, 2), "matcher": matched.matcher,
        "classified": classified, "selection": selection,
    }
    print(f"{gold.topic:26s} Absätze {report.paragraphs:3d} entschieden {report.answered:3d} Rückfall "
          f"{report.fallback:2d} Aufrufe {report.calls} Tokens {report.total_tokens:6d} Wand {wall:5.1f} s", flush=True)

total = aggregate(evaluations)
summary = {
    "topics": len(topics), "tokens": spent, "calls": sum(t["calls"] for t in topics.values()),
    "macro_f1": total.macro_f1, "micro_f1": total.micro_f1, "assigned": total.assigned,
    "misassigned": total.misassigned, "top2_judged": judged, "top2_correct": correct,
    "same_as_first_run": same, "compared_with_first_run": compared,
}
out_path.write_text(json.dumps({"summary": summary, "topics": topics}, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1))
