"""Messskript M62 (03.10.2026): der KI-Zuordner (matcher=llm) mit reasoning_effort low und none, je Absatz.

Jan: „ki zuordner wäre ein großer zeitgewinn - aber wir sollten den qualitätsverlust nochmal genauer prüfen“. M59 maß
am Gold drei Läufe je Aufwand und nur Summen; hier zählt jeder Absatz: welcher Baustein, ob das Modell entschied oder
die Regeln blieben, und warum. Die Läufe wechseln sich ab (low, none, low, …), damit die Tageszeit beide trifft.
Einmal-Container mit den Archiven, LLM über OpenAI direkt (mc_openai_direkt.py), frische Antworten:

  cat mc_openai_direkt.py mc_zuordnung_none.py | docker compose run --rm --no-deps -T -v <repo>/eval/gold:/gold \
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY \
      -e LLM_MAX_TOKENS_PER_REQUEST=400000 -e LLM_MAX_CONCURRENCY=4 api python - <läufe je Aufwand> [<aufwand>...]

Ergebnis als JSON nach der Zeile JSON-START: je Lauf macro- und micro-F1, Tokens, Sekunden, Rückfälle, die
unbekannten Bausteine im Wortlaut, und je Absatz Gold, Vorhersage und Herkunft. Auswertung im Messprotokoll (M62).
"""

# --- M62: matcher=llm with reasoning effort low and none, per paragraph ---
import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

install()
import app.matching.llm_assignment as llm_assignment
from app.domain.requests import GenerateRequest
from app.main import build_registry, build_service
from app.matching.eval import aggregate, align, evaluate, predictions_from_classification
from app.matching.gold import load_gold
from app.settings import get_settings
from app.templates.schema import block_key
from app.templates.manager import TemplateManager

runs_per_effort = int(sys.argv[1])
efforts = sys.argv[2:] or ["low", "none"]
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
client = service.llm.client
shipped = dict(client.reasoning_efforts)

pools = []
for path in sorted(Path("/gold").glob("*.jsonl")):
    gold = load_gold(path)
    prepared = service.prepare(GenerateRequest(topic=gold.topic, parts=["world"]))  # the rules' corpus, as labelled
    alignment = align(gold, prepared.chunks)
    chunks = [c for c in prepared.chunks if c.chunk_id in alignment.gold_by_chunk]
    pools.append((gold, alignment, replace(prepared, chunks=chunks)))
print(f"# {len(pools)} topics, {sum(len(p.chunks) for _, _, p in pools)} paragraphs", file=sys.stderr, flush=True)

lock = threading.Lock()
seen = {"answers": [], "decided": None}
original_parse, original_combine = llm_assignment.parse_assignment, llm_assignment._combine


def parsing(text):
    parsed = original_parse(text)
    if threading.current_thread() is threading.main_thread():  # the batches' threads only check readability
        with lock:
            seen["answers"].append(parsed)
    return parsed


def combining(template, offered, decided, rule_based, skipped):
    seen["decided"] = dict(decided)
    return original_combine(template, offered, decided, rule_based, skipped)


llm_assignment.parse_assignment = parsing
llm_assignment._combine = combining

out = {"efforts": efforts, "runs": []}
order = [effort for _ in range(runs_per_effort) for effort in efforts]
for number, effort in enumerate(order, start=1):
    client.reasoning_efforts = {**shipped, "paragraph_assignment": effort}
    evals, per_topic, paragraphs, unknown = [], {}, {}, {}
    totals = {"tokens": 0, "completion": 0, "calls": 0, "fallback": 0, "unknown_keys": 0, "fallbacks": {}}
    started_all = time.perf_counter()
    for gold, alignment, pool in pools:
        seen["answers"], seen["decided"] = [], None
        started = time.perf_counter()
        matched = service.match(pool, "llm", 12_000)
        per_topic[gold.topic] = round(time.perf_counter() - started, 2)
        report = matched.llm
        totals["tokens"] += report.total_tokens
        totals["completion"] += report.completion_tokens
        totals["calls"] += report.calls
        totals["fallback"] += report.fallback
        totals["unknown_keys"] += report.unknown_keys
        for reason, count in report.fallbacks.items():
            totals["fallbacks"][reason] = totals["fallbacks"].get(reason, 0) + count
        keys = {block_key(slot.slot) for slot in pool.template.content_slots()}
        for parsed in seen["answers"]:
            for key, _ in (parsed or {}).values():
                if key != llm_assignment.NONE_KEY and key not in keys:
                    unknown[key] = unknown.get(key, 0) + 1
        slot_keys = [slot.slot for slot in pool.template.content_slots()]
        key_of = {slot.id: slot.slot for slot in pool.template.slots}
        classified = predictions_from_classification(matched.assignment.classified, pool.template)
        evals.append(evaluate(gold.topic, alignment.gold_by_chunk, classified, slot_keys, matcher=effort))
        decided = seen["decided"] or {}
        paragraphs[gold.topic] = {
            chunk_id: {
                "gold": label,
                "pred": classified.get(chunk_id),
                "by": "llm" if chunk_id in decided else "rules",
                "conf": round(decided[chunk_id][1], 2) if chunk_id in decided else None,
                "llm": key_of.get(decided[chunk_id][0]) if chunk_id in decided and decided[chunk_id][0] else None,
            }
            for chunk_id, label in alignment.gold_by_chunk.items()
        }
    total = aggregate(evals)
    run = {"run": number, "effort": effort, "macro_f1": round(total.macro_f1, 4), "micro_f1": round(total.micro_f1, 4),
           "assigned": total.assigned, "misassigned": total.misassigned, "missed": total.missed, **totals,
           "seconds": round(time.perf_counter() - started_all, 1), "seconds_per_topic": per_topic,
           "slots": {m.slot: {"tp": m.tp, "fp": m.fp, "fn": m.fn, "support": m.support} for m in total.slots},
           "unknown": unknown, "paragraphs": paragraphs}
    out["runs"].append(run)
    print(f"# run {number} {effort}: macro {total.macro_f1:.3f} micro {total.micro_f1:.3f} tokens {totals['tokens']} "
          f"fallback {totals['fallback']} unknown {totals['unknown_keys']} {run['seconds']} s", file=sys.stderr, flush=True)
print("JSON-START")
print(json.dumps(out, ensure_ascii=False))
