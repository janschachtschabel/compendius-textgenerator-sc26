"""Step 1 (test app venv): score every (block, paragraph) pair with one of the test app's models.

The texts are exactly those the service's rankers compare (app/matching/base.py): the block representation is
title, description, inclusions, sub-items and search queries (no exclusions); the paragraph representation is the
heading path plus the text. So the models can later run as rankers inside the service's own path
(mc_model_variants.py) and be measured against the service's gold standard.

Models: minilm (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2, cosine), cross_encoder
(cross-encoder/msmarco-MiniLM-L6-en-de-v1, sigmoid of the logit, all pairs), qa (deutsche-telekom/electra-base-de-squad2
with the test app's question per block, on the 15 best MiniLM candidates per block, scored like the test app's
extractive_qa matcher without its keyword boosts). The result file is written after every topic.

Usage (test app venv, cwd kompendium-test):
    python mc_model_scores.py <export.json> <minilm|cross_encoder> <out.json>
    python mc_model_scores.py <export.json> qa <out.json> <minilm_scores.json>
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402

export_path, model_name, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
export = json.load(open(export_path, encoding="utf-8"))
torch.set_num_threads(8)


def slot_representation(slot: dict) -> str:  # mirrors app/matching/base.py
    parts = [slot["title"], slot["description"], slot["inclusions"]]
    if slot.get("sub_items"):
        parts.append(" ".join(slot["sub_items"]))
    if slot.get("search_queries"):
        parts.append(" ".join(slot["search_queries"]))
    return ". ".join(p for p in parts if p).strip()


def chunk_representation(chunk: dict) -> str:  # mirrors app/matching/base.py
    return f"{chunk['full_heading']}. {chunk['text']}"


if model_name == "minilm":
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
elif model_name == "cross_encoder":
    from sentence_transformers import CrossEncoder

    model = CrossEncoder("cross-encoder/msmarco-MiniLM-L6-en-de-v1", max_length=512)
elif model_name == "qa":
    from transformers import AutoModelForQuestionAnswering, AutoTokenizer

    from kompendium.matching.extractive_qa_matcher import build_slot_question

    tokenizer = AutoTokenizer.from_pretrained("deutsche-telekom/electra-base-de-squad2")
    model = AutoModelForQuestionAnswering.from_pretrained("deutsche-telekom/electra-base-de-squad2").eval()
    MINILM = json.load(open(sys.argv[4], encoding="utf-8"))["topics"]  # candidates come from the MiniLM run
    QA_CANDIDATES = 15  # like the service's CANDIDATES_PER_SLOT
else:
    sys.exit(f"unknown model {model_name}")


def qa_margins(question: str, texts: list[str], batch: int = 16) -> list[float]:
    margins: list[float] = []
    for start in range(0, len(texts), batch):
        part = texts[start : start + batch]
        inputs = tokenizer([question] * len(part), part, return_tensors="pt", max_length=384, truncation="only_second",
                           padding=True)
        with torch.no_grad():
            out = model(**inputs)
        for row in range(len(part)):
            starts, ends = out.start_logits[row], out.end_logits[row]
            no_answer = float(starts[0] + ends[0])
            context = (inputs["token_type_ids"][row] == 1) & (inputs["attention_mask"][row] == 1)
            s = starts.masked_fill(~context, -1e4)
            e = ends.masked_fill(~context, -1e4)
            best_start = int(torch.argmax(s))
            best_end = best_start + int(torch.argmax(e[best_start : best_start + 35]))
            margins.append(max(0.0, float(s[best_start] + e[best_end]) - no_answer))
    return margins


result: dict[str, dict] = {"model": model_name, "topics": {}}
for topic in export["topics"]:
    name = topic["topic"]
    slots = [s for s in topic["slots"] if not s.get("generator")]
    chunks = topic["chunks"]
    ids = [c["chunk_id"] for c in chunks]
    started = time.perf_counter()
    scores: dict[str, dict[str, float]] = {}
    if model_name == "minilm":
        chunk_vecs = model.encode([chunk_representation(c) for c in chunks], normalize_embeddings=True,
                                  convert_to_tensor=True, show_progress_bar=False)
        slot_vecs = model.encode([slot_representation(s) for s in slots], normalize_embeddings=True,
                                 convert_to_tensor=True, show_progress_bar=False)
        sims = (slot_vecs @ chunk_vecs.T).cpu().tolist()
        for slot, row in zip(slots, sims):
            scores[slot["slot"]] = {cid: round(v, 5) for cid, v in zip(ids, row)}
    elif model_name == "cross_encoder":
        texts = [chunk_representation(c) for c in chunks]
        for slot in slots:
            rep = slot_representation(slot)
            logits = model.predict([(rep, t) for t in texts], batch_size=64, show_progress_bar=False,
                                   activation_fn=torch.nn.Identity())
            scores[slot["slot"]] = {cid: round(1 / (1 + math.exp(-float(v))), 5) for cid, v in zip(ids, logits)}
    else:
        # As in the test app: MiniLM picks the candidates, the QA model checks only those (all pairs took ~5 pairs/s
        # on this CPU, 746 s for one topic). Score as in extractive_qa_matcher.py without its keyword boosts:
        # answer found -> 0.6 * min(1, margin / 10) + 0.4 * similarity, otherwise 0.05 * similarity.
        minilm = MINILM[name]["scores"]
        text_of = {c["chunk_id"]: c["text"] for c in chunks}
        pairs = 0
        for slot in slots:
            sims = minilm[slot["slot"]]
            candidates = sorted(ids, key=lambda cid: -sims[cid])[:QA_CANDIDATES]
            margins = qa_margins(build_slot_question(slot, topic=name), [text_of[cid] for cid in candidates])
            pairs += len(candidates)
            scores[slot["slot"]] = {
                cid: round(0.6 * min(1.0, m / 10.0) + 0.4 * max(0.0, sims[cid]) if m > 0 else 0.05 * max(0.0, sims[cid]), 5)
                for cid, m in zip(candidates, margins)
            }
    seconds = round(time.perf_counter() - started, 2)
    pair_count = pairs if model_name == "qa" else len(slots) * len(chunks)
    result["topics"][name] = {"seconds": seconds, "pairs": pair_count, "scores": scores}
    print(f"{model_name:14s} {name:24s} Absätze {len(chunks):4d} Paare {pair_count:5d} {seconds:7.1f} s", flush=True)
    json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)  # after every topic

print("written", out_path)
