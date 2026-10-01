"""M46: do the batches of matcher=llm read their shared opening from the b-api's prompt cache, and how should they be
sent? Three schedules of the same batches, each on topics of its own (the b-api answers a repeated request from its
response cache, usage included), in best-quality, with the layout of paragraph_assignment v1 (stand c59afdb):

a  all batches at once (as shipped: LLM_MAX_CONCURRENCY 10)
b  the first batch alone, the others after its answer
c  the first batch, the others two seconds after it

The key comes from B_API_KEY. 35,000 to 61,000 tokens per topic.

Usage (from the project folder): python mc_cache_zuordnung_ablauf.py <out.json> a:<topic>,<topic> b:<topic> c:<topic>
"""

from __future__ import annotations

import contextvars
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import app.matching.llm_assignment as assignment  # noqa: E402
from app.cli_common import cli_service  # noqa: E402
from app.concurrency import map_in_threads  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]


def first_then_rest(fn, items, workers):
    if len(items) < 2:
        return map_in_threads(fn, items, workers)
    return map_in_threads(fn, items[:1], 1) + map_in_threads(fn, items[1:], workers)


def head_start(seconds):
    def run(fn, items, workers):
        if len(items) < 2:
            return map_in_threads(fn, items, workers)
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(contextvars.copy_context().run, fn, items[0])
            time.sleep(seconds)
            rest = map_in_threads(fn, items[1:], workers)
            return [first.result(), *rest]
    return run


SCHEDULES = {"a": map_in_threads, "b": first_then_rest, "c": head_start(2.0)}

out_path = Path(sys.argv[1])
plan = [(arg.split(":", 1)[0], topic) for arg in sys.argv[2:] for topic in arg.split(":", 1)[1].split(",")]
service = cli_service(ZIMS)
if service.llm is None:
    raise SystemExit("LLM_ENABLED did not reach the settings")
rows = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
for schedule, topic in plan:
    assignment.map_in_threads = SCHEDULES[schedule]
    start = time.monotonic()
    result = service.generate(GenerateRequest(topic=topic, parts=["world"], preset="best-quality"))
    took = time.monotonic() - start
    matching = (result.audit.llm or {}).get("matching") or {}
    tokens = result.audit.llm_tokens or {}
    rows.append({"schedule": schedule, "topic": topic, "s": round(took, 1), "match_ms": result.audit.timings_ms.get("match"),
                 "tokens": tokens, "matching": {k: matching.get(k) for k in ("calls", "paragraphs", "tokens", "fallback")}})
    print(f"{schedule} | {topic} | {took:.0f}s | match {result.audit.timings_ms.get('match')} ms | calls {tokens.get('calls')} "
          f"| prompt {tokens.get('prompt')} | cached {tokens.get('cached')} | matching {rows[-1]['matching']}", flush=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
