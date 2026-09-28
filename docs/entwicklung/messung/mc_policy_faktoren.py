"""What each factor of the matching policy is worth on the gold standard (M44, audit 2026-09-27 WA-02).

The six factors of ``_score_candidate`` (app/matching/policy.py) carried no measurement. For each, the ten gold topics
of eval/gold are matched once with the factor neutral (1.0) and compared with the shipped value, in the service's
flow: the corpus of llm-free (service.prepare, as compendium eval builds it), the profiles' local strategy
hybrid_light with the service's Model2Vec model, target_length 12,000. Each topic is prepared once; only the
assignment runs again. Classification before the budgets (the quality gate of eval/README) and what the text prints.

Usage, in the API container of the development setup (archives and /models/m2v there), with the gold copied to /tmp:
python /tmp/mc_policy_faktoren.py /tmp/gold /tmp/m44.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from app.cli_common import cli_service
from app.domain.requests import GenerateRequest
from app.matching import policy
from app.matching.eval import aggregate, align, evaluate, predictions_from_assignment, predictions_from_classification
from app.matching.gold import load_gold

STRATEGY = "hybrid_light"
TARGET_LENGTH = 12_000  # DEFAULT_TARGET_LENGTH of compendium eval
FACTORS = (
    "SUBAREA_BOOST",
    "OTHER_HEADING_FACTOR",
    "SECTION_LEAD_BOOST",
    "EXCLUSION_FACTOR",
    "FIRST_SOURCE_BOOST",
    "PREFERRED_SOURCE_BOOST",
)

gold_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2])
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
service = cli_service(None)
if not service.settings.model2vec_path:
    raise SystemExit("MODEL2VEC_PATH ist leer: gemessen wird mit der Strategie der Profile, samt Model2Vec")

prepared_topics = []
for path in sorted(gold_dir.glob("*.jsonl")):
    gold = load_gold(path)
    prepared = service.prepare(GenerateRequest(topic=gold.topic, template_id=gold.template_id))
    prepared_topics.append((gold, prepared, align(gold, prepared.chunks)))
    print(f"vorbereitet: {gold.topic} ({len(prepared.chunks)} Absätze)", flush=True)


def measure() -> dict[str, Any]:
    classified, printed, per_topic = [], [], {}
    for gold, prepared, alignment in prepared_topics:
        title = prepared.resolution.title or gold.topic
        slot_keys = [slot.slot for slot in prepared.template.content_slots()]
        matched = service.match(prepared, STRATEGY, TARGET_LENGTH)
        before = evaluate(
            title,
            alignment.gold_by_chunk,
            predictions_from_classification(matched.assignment.classified, prepared.template),
            slot_keys,
            matcher=STRATEGY,
        )
        shown = evaluate(
            title,
            alignment.gold_by_chunk,
            predictions_from_assignment(matched.assignment.assigned, prepared.template),
            slot_keys,
            matcher=STRATEGY,
        )
        classified.append(before)
        printed.append(shown)
        per_topic[gold.topic] = {"macro_f1": round(before.macro_f1, 3), "gedruckt_macro_f1": round(shown.macro_f1, 3)}
    whole, text = aggregate(classified), aggregate(printed)
    return {
        "macro_f1": round(whole.macro_f1, 4),
        "micro_f1": round(whole.micro_f1, 4),
        "gedruckt_macro_f1": round(text.macro_f1, 4),
        "je_thema": per_topic,
    }


started = time.perf_counter()
results: dict[str, Any] = {"ausgeliefert": measure()}
print(f"ausgeliefert: {results['ausgeliefert']['macro_f1']} / gedruckt {results['ausgeliefert']['gedruckt_macro_f1']}")
for name in FACTORS:
    shipped = getattr(policy, name)
    setattr(policy, name, 1.0)
    try:
        results[name] = {"wert": shipped, **measure()}
    finally:
        setattr(policy, name, shipped)
    row = results[name]
    print(f"{name} {shipped} -> 1.0: {row['macro_f1']} / gedruckt {row['gedruckt_macro_f1']}", flush=True)
results["sekunden"] = round(time.perf_counter() - started, 1)
out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Ergebnis: {out_path}")
