"""What the request budget did to matcher=llm before D39, recomputed without the b-api (project venv, no tokens).

Per topic the paragraphs matcher=llm offers, cut into batches as the service cuts them, and what each batch reserves
before its call (estimated prompt plus answer limit with the room to think). Before D39 a batch the budget could not
hold fell back to the rules at once; since the calls take seconds, every batch reserved before the first one settled,
so the budget granted the batches in order until the next did not fit. For the five topics of M13 this gives exactly
the 194 paragraphs that fell back there.

Usage: python mc_budget_nachrechnung.py <out.json> <budget> <Thema>...
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

os.environ.pop("LLM_ENABLED", None)  # the corpus is all that is needed
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.llm.budget import estimate_tokens  # noqa: E402
from app.llm.client import BApiClient  # noqa: E402
from app.matching.llm_assignment import BATCH_SIZE, OUTPUT_TOKENS_PER_PARAGRAPH, render_messages  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]

out_path, budget, topics = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]
service = cli_service(ZIMS)
model = BApiClient("https://b-api.invalid", "keiner", provider="openai", model=service.settings.b_api_model)

rows: list[dict] = []
for topic in topics:
    prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"], article_choice="rule-based"))
    generated = {slot.slot for slot in prepared.template.slots if slot.is_generated}
    offered = [chunk for chunk in prepared.chunks if chunk.lexicon_slot not in generated]
    title = prepared.resolution.title or prepared.normalized.topic
    reserved, turned_away, needs = 0, 0, []
    for start in range(0, len(offered), BATCH_SIZE):
        batch = offered[start : start + BATCH_SIZE]
        messages = render_messages(prepared.template, title, batch, prepared.sources_by_id)
        need = estimate_tokens("".join(m["content"] for m in messages)) + model.completion_limit(
            OUTPUT_TOKENS_PER_PARAGRAPH * len(batch)
        )
        needs.append(need)
        if reserved + need > budget:
            turned_away += len(batch)
        else:
            reserved += need
    rows.append({
        "thema": topic, "artikel": title, "absaetze": len(offered), "stapel": math.ceil(len(offered) / BATCH_SIZE),
        "reservierungen": needs, "rueckfall_ohne_warten": turned_away,
    })
    print(f"{topic:22s} {len(offered):4d} Absätze, Reservierungen {needs}, Rückfall ohne Warten {turned_away}")

total = {"absaetze": sum(r["absaetze"] for r in rows), "rueckfall_ohne_warten": sum(r["rueckfall_ohne_warten"] for r in rows)}
print(total)
out_path.write_text(
    json.dumps({"budget": budget, "zusammen": total, "themen": rows}, ensure_ascii=False, indent=1), "utf-8"
)
