"""Result tables for 03-matching.md and 05-messprotokoll.md, straight from the data (project venv).

Everything is measured on the service's gold standard: macro/micro-F1 via app.matching.eval, "richtig unter Top 2"
with the definitions of mc_eval.py. Times: the service's own rankers as measured (mean over the ten topics, with a
warm-up); the test app's models as the median time per topic to score what they score (all pairs, or the MiniLM
candidates for QA); the cross-encoder re-ranking as the standard's time plus the cross-encoder's time per pair times
the candidate pairs of the topic. The LLM from its two runs: the first one by script (latency, extrapolation) and
matcher=llm through the service (mc_llm_dienst.py). Rounding half up, German number format.

Usage: python mc_final_tables.py <export_all.json> <scores_minilm> <scores_ce> <scores_qa> <llm_raw.json> <out.json>
           <llm_dienst.json>
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from decimal import ROUND_HALF_UP, Decimal

from app.matching.eval import aggregate, evaluate

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

export = json.load(open(sys.argv[1], encoding="utf-8"))
model_scores = {name: json.load(open(path, encoding="utf-8"))["topics"]
                for name, path in zip(("minilm", "cross_encoder", "qa"), sys.argv[2:5], strict=True)}
llm_raw = json.load(open(sys.argv[5], encoding="utf-8"))
out_path = sys.argv[6]
llm_service = json.load(open(sys.argv[7], encoding="utf-8"))["summary"]


def de(value: float, places: str) -> str:
    rounded = Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    text = f"{rounded:,}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def selection_stats(selection: dict, gold: dict, slot_keys: list[str], k: int = 2) -> tuple[int, int, int]:
    judged = correct = covered = 0
    for slot in slot_keys:
        items = selection.get(slot, [])[:k]
        if not items:
            continue
        covered += 1
        for chunk_id, _ in items:
            if chunk_id in gold:
                judged += 1
                correct += gold[chunk_id] == slot
    return judged, correct, covered


def metrics(pool: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for topic in export["topics"]:
        slot_keys = [s["slot"] for s in topic["slots"] if not s.get("generator")]
        for label, run in topic["mine"][pool].items():
            row = rows.setdefault(label, {"eval": [], "judged": 0, "correct": 0, "covered": 0, "ms": [], "n": 0,
                                          "candidate_pairs": [], "candidate_chunks": [], "pool_chunks": []})
            row["eval"].append(evaluate(topic["topic"], topic["gold"], run["classified"], slot_keys, matcher=label))
            judged, correct, covered = selection_stats(run["selection"], topic["gold"], slot_keys)
            row["judged"] += judged
            row["correct"] += correct
            row["covered"] += covered
            row["ms"].append(run.get("ms", 0))
            row["n"] += 1
            for key in ("candidate_pairs", "candidate_chunks", "pool_chunks"):
                if run.get(key) is not None:
                    row[key].append(run[key])
    result = {}
    for label, row in rows.items():
        total = aggregate(row["eval"])
        result[label] = {
            "macro": total.macro_f1, "micro": total.micro_f1, "top2": row["correct"] / max(row["judged"], 1),
            "covered": row["covered"] / row["n"], "ms_mean": statistics.mean(row["ms"]), "topics": row["n"],
            "assigned": total.assigned, "misassigned": total.misassigned,
            "candidate_pairs": row["candidate_pairs"], "candidate_chunks": row["candidate_chunks"],
            "pool_chunks": row["pool_chunks"],
        }
    return result


full, gold_pool = metrics("full"), metrics("gold")

# times of the test app's models per topic (seconds), and the cross-encoder's time per pair
model_seconds = {name: statistics.median(t["seconds"] for t in topics.values()) for name, topics in model_scores.items()}
ce_per_pair = sum(t["seconds"] for t in model_scores["cross_encoder"].values()) / sum(
    t["pairs"] for t in model_scores["cross_encoder"].values())
standard_s = full["hybrid_light + M2V"]["ms_mean"] / 1000
rerank_label = "hybrid_light + M2V, Cross-Encoder sortiert um"
rerank_seconds = statistics.median(standard_s + p * ce_per_pair for p in full[rerank_label]["candidate_pairs"])
fused_label = "hybrid_light + M2V + Cross-Encoder (fusioniert)"
seconds = {
    "MiniLM-Satzvektoren allein": model_seconds["minilm"],
    "Cross-Encoder allein": model_seconds["cross_encoder"],
    "Frage-Antwort-Modell allein": model_seconds["qa"],
    rerank_label: rerank_seconds,
    fused_label: standard_s + model_seconds["cross_encoder"],
}

ORDER = [
    ("lexicon_only", "nur Überschriften-Lexikon (`lexicon_only`)"),
    ("bm25", "BM25 (`bm25`)"),
    ("char_tfidf", "Zeichen-TF-IDF (`char_tfidf`)"),
    ("Model2Vec allein", "Model2Vec allein"),
    ("MiniLM-Satzvektoren allein", "MiniLM-Satzvektoren allein (Modell aus `e5_onnx`)"),
    ("Cross-Encoder allein", "Cross-Encoder allein (Modell der Testapp)"),
    ("Frage-Antwort-Modell allein", "Frage-Antwort-Modell (wie `extractive_qa`, MiniLM-Kandidaten)"),
    ("BM25 + Model2Vec", "BM25 + Model2Vec"),
    ("hybrid_light (ohne M2V)", "`hybrid_light` ohne Model2Vec (BM25 + Zeichen-TF-IDF)"),
    ("hybrid_light + M2V", "**`hybrid_light` + Model2Vec (Standard)**"),
    (rerank_label, "Standard, Kandidaten vom Cross-Encoder umsortiert"),
    (fused_label, "Standard + Cross-Encoder als vierter Ranker"),
]


def seconds_of(label: str) -> float:
    return seconds.get(label, full[label]["ms_mean"] / 1000)


def fmt_seconds(value: float) -> str:
    return de(value, "0.01") + " s" if value < 1 else de(value, "0.1") + " s"


lines = ["| Verfahren | macro-F1 | micro-F1 | richtig unter Top 2 | belegte Bausteine (von 10) | Rechenzeit je Thema |",
         "|---|---|---|---|---|---|"]
for label, title in ORDER:
    m = full[label]
    lines.append(f"| {title} | {de(m['macro'], '0.01')} | {de(m['micro'], '0.01')} | {de(100 * m['top2'], '1')} % | "
                 f"{de(m['covered'], '0.1')} | {fmt_seconds(seconds_of(label))} |")
print("\n".join(lines))

# LLM on the gold pool
llm_topics = llm_raw["topics"].values()
llm_wall = statistics.median(t["wall_seconds"] for t in llm_topics)
llm_tokens_per_paragraph = llm_raw["spent"]["tokens"] / sum(t["paragraphs"] for t in llm_topics)
latencies = [c["seconds"] for t in llm_topics for c in t["calls"] if "seconds" in c]
call_latency = statistics.median(latencies)
full_paragraphs = [len(t["chunks"]) for t in export["topics"]]
per_topic_tokens_full = [p * llm_tokens_per_paragraph for p in full_paragraphs]
per_topic_seconds_full = [math.ceil(math.ceil(p / 25) / 4) * call_latency for p in full_paragraphs]
candidate_chunks = full[rerank_label]["candidate_chunks"]
per_topic_tokens_candidates = [c * llm_tokens_per_paragraph for c in candidate_chunks]

print("\nGoldpool:")
gold_lines = ["| Verfahren | macro-F1 | micro-F1 | richtig unter Top 2 | falsch zugeordnet |", "|---|---|---|---|---|"]
LLM_ROWS = [("matcher=llm (Dienst)", "**`matcher=llm` im Dienst**"),
            ("LLM gpt-5.6-luna", "`gpt-5.6-luna`, erste Messung mit Skript")]
for label, title in LLM_ROWS + ORDER:
    m = gold_pool[label]
    gold_lines.append(f"| {title} | {de(m['macro'], '0.01')} | {de(m['micro'], '0.01')} | {de(100 * m['top2'], '1')} % | "
                      f"{m['misassigned']} von {m['assigned']} |")
print("\n".join(gold_lines))
print(f"\nLLM: Tokens {llm_raw['spent']['tokens']}, Aufrufe {llm_raw['spent']['calls']}, je Absatz "
      f"{llm_tokens_per_paragraph:.0f}, Latenz je Aufruf Median {call_latency:.1f} s, Wandzeit je Thema (Goldpool) "
      f"Median {llm_wall:.1f} s")
print(f"LLM hochgerechnet auf den vollen Pool je Thema: Tokens Median {statistics.median(per_topic_tokens_full):.0f} "
      f"(min {min(per_topic_tokens_full):.0f}, max {max(per_topic_tokens_full):.0f}), Sekunden Median "
      f"{statistics.median(per_topic_seconds_full):.0f} (max {max(per_topic_seconds_full):.0f})")
print(f"LLM nur über die Kandidaten der Ranker: Absätze Median {statistics.median(candidate_chunks):.0f} von "
      f"{statistics.median(full_paragraphs):.0f}, Tokens Median {statistics.median(per_topic_tokens_candidates):.0f}")
print(f"Modellzeiten je Thema (Median): {model_seconds}; Cross-Encoder je Paar {ce_per_pair * 1000:.1f} ms; "
      f"Reranking-Paare je Thema Median {statistics.median(full[rerank_label]['candidate_pairs'])}")

print(f"matcher=llm im Dienst: Tokens {llm_service['tokens']}, Aufrufe {llm_service['calls']}, gleich wie im ersten Lauf "
      f"{llm_service['same_as_first_run']} von {llm_service['compared_with_first_run']}")

json.dump({"full": full, "gold": gold_pool, "seconds": seconds, "model_seconds": model_seconds,
           "llm_service": llm_service,
           "ce_per_pair_s": ce_per_pair, "llm": {"tokens": llm_raw["spent"]["tokens"], "calls": llm_raw["spent"]["calls"],
           "tokens_per_paragraph": llm_tokens_per_paragraph, "call_latency_median_s": call_latency,
           "wall_median_s": llm_wall, "full_pool_tokens_per_topic": per_topic_tokens_full,
           "full_pool_seconds_per_topic": per_topic_seconds_full, "candidate_chunks": candidate_chunks}},
          open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
