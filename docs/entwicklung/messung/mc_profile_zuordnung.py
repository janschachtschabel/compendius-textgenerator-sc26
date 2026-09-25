"""Zuordnung (macro-F1 on eval/gold) of the standard strategy on the corpus of llm-free and of balanced (M27).

compendium eval prepares every gold topic without the LLM article choice (compare_topic), so the decision paper has
no measured value for balanced. This runs both ways on the same gold and the same strategy:

- llm-free: service.prepare(request), as compendium eval does
- balanced: the article choice job /compendium opens for article_choice=llm, so the LLM decides an unsure article
  and drops the full-text hits it rates unfit (hit check)

Per topic: main article, chunks, labels scored and stale, what the hit check dropped, tokens; pooled per way the
classification before the budgets (the quality gate of eval/README) and what the text prints.

Usage (project venv, from the project root; B_API_KEY in .env, never printed):
python docs/entwicklung/messung/mc_profile_zuordnung.py <out.json> --m2v <model directory>
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ["LLM_ENABLED"] = "true"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.llm.deadline import Deadline  # noqa: E402
from app.matching.eval import (  # noqa: E402
    aggregate,
    align,
    evaluate,
    predictions_from_assignment,
    predictions_from_classification,
)
from app.matching.gold import load_gold  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
STRATEGY = "hybrid_light"
TARGET_LENGTH = 12_000  # DEFAULT_TARGET_LENGTH of compendium eval
WAYS = ("llm-free", "balanced")

out_path = Path(sys.argv[1])
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
service = cli_service(ZIMS)
service.settings.model2vec_path = sys.argv[sys.argv.index("--m2v") + 1]
if service.llm_unavailable() is not None or service.llm is None:
    raise SystemExit(f"LLM nicht verfügbar: {service.llm_unavailable()}")

rows: dict[str, dict[str, Any]] = {}
pooled: dict[str, dict[str, list[Any]]] = {way: {"classified": [], "printed": [], "goldpool": []} for way in WAYS}
for path in sorted(Path("eval/gold").glob("*.jsonl")):
    gold = load_gold(path)
    request = GenerateRequest(topic=gold.topic, template_id=gold.template_id)
    row: dict[str, Any] = {}
    for way in WAYS:
        started = time.perf_counter()
        if way == "llm-free":
            prepared, tokens, dropped = service.prepare(request), 0, []
        else:
            deadline = Deadline(service.settings.request_timeout_s)
            _, note, choice = service.article_choice_job("llm", deadline)
            if choice is None:
                raise SystemExit(f"{gold.topic}: keine Artikelwahl ({note})")
            prepared = service.prepare(request, deadline, choice)
            tokens = choice.budget.used
            dropped = list(prepared.hit_check.dropped) if prepared.hit_check is not None else []
        seconds = time.perf_counter() - started
        title = prepared.resolution.title or gold.topic
        slot_keys = [slot.slot for slot in prepared.template.content_slots()]
        alignment = align(gold, prepared.chunks)
        matched = service.match(prepared, STRATEGY, TARGET_LENGTH)
        classified = evaluate(
            title,
            alignment.gold_by_chunk,
            predictions_from_classification(matched.assignment.classified, prepared.template),
            slot_keys,
            matcher=way,
        )
        printed = evaluate(
            title,
            alignment.gold_by_chunk,
            predictions_from_assignment(matched.assignment.assigned, prepared.template),
            slot_keys,
            matcher=way,
        )
        classified.stale_labels = printed.stale_labels = len(alignment.stale)
        # The gold pool of M5/M12/M15: only the labelled paragraphs are candidates (the decision paper's 0,43)
        corpus = prepared.chunks
        prepared.chunks = [chunk for chunk in corpus if chunk.chunk_id in alignment.gold_by_chunk]
        try:
            in_pool = service.match(prepared, STRATEGY, TARGET_LENGTH)
        finally:
            prepared.chunks = corpus
        goldpool = evaluate(
            title,
            alignment.gold_by_chunk,
            predictions_from_classification(in_pool.assignment.classified, prepared.template),
            slot_keys,
            matcher=way,
        )
        pooled[way]["classified"].append(classified)
        pooled[way]["printed"].append(printed)
        pooled[way]["goldpool"].append(goldpool)
        row[way] = {
            "hauptartikel": title,
            "chunks": len(prepared.chunks),
            "labels_bewertet": classified.labeled,
            "labels_veraltet": len(alignment.stale),
            "macro_f1": round(classified.macro_f1, 3),
            "micro_f1": round(classified.micro_f1, 3),
            "gedruckt_macro_f1": round(printed.macro_f1, 3),
            "goldpool_macro_f1": round(goldpool.macro_f1, 3),
            "fehlbelegt": classified.misassigned,
            "verworfen_durch_trefferpruefung": dropped,
            "tokens": tokens,
            "sekunden_vorbereitung": round(seconds, 2),
        }
    rows[gold.topic] = row
    free, bal = row["llm-free"], row["balanced"]
    print(
        f"{gold.topic:26} {free['hauptartikel'][:22]:22} | {bal['hauptartikel'][:22]:22} "
        f"chunks {free['chunks']:3}/{bal['chunks']:3} labels {free['labels_bewertet']:3}/{bal['labels_bewertet']:3} "
        f"macro {free['macro_f1']:.3f}/{bal['macro_f1']:.3f} dropped {len(bal['verworfen_durch_trefferpruefung'])} "
        f"tokens {bal['tokens']}",
        flush=True,
    )

summary: dict[str, Any] = {}
for way in WAYS:
    whole = aggregate(pooled[way]["classified"])
    shown = aggregate(pooled[way]["printed"])
    labelled_only = aggregate(pooled[way]["goldpool"])
    summary[way] = {
        "macro_f1": round(whole.macro_f1, 4),
        "micro_f1": round(whole.micro_f1, 4),
        "goldpool_macro_f1": round(labelled_only.macro_f1, 4),
        "goldpool_micro_f1": round(labelled_only.micro_f1, 4),
        "labels_bewertet": whole.labeled,
        "labels_veraltet": whole.stale_labels,
        "fehlbelegt": whole.misassigned,
        "verpasst": whole.missed,
        "gedruckt_macro_f1": round(shown.macro_f1, 4),
        "gedruckt_micro_f1": round(shown.micro_f1, 4),
        "je_baustein_f1": {m.slot: round(m.f1, 3) for m in whole.slots if m.support > 0},
    }
    print(f"{way:9} {json.dumps(summary[way], ensure_ascii=False)}")

out_path.write_text(
    json.dumps({"strategie": STRATEGY, "zusammenfassung": summary, "themen": rows}, ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(f"\n{len(rows)} Themen nach {out_path}")
