"""Blind LLM judge (gpt-5.6-luna via b-api) over all methods on held-out topics, code state 2.0.0.

For every topic and building block the union of the top-2 selections of all methods is rated once, shuffled and
anonymised (method names never reach the model). Prompt and model are those of mc_judge.py (2026-09-18), so
ratings are comparable. The cache is keyed by topic, block, a signature of the block's prompt text and a hash of
the paragraph text; ratings of 2026-09-18 are reused only where paragraph text and block text are unchanged.
A hard token limit stops the run before the budget agreed with Jan is exceeded.

Usage (project venv): python mc_judge_v200.py <heldout_export.json> <cache.json> <token_limit> <testapp.json>...
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import random
import sys
from collections import defaultdict
from pathlib import Path

from app.llm.client import BApiClient, LlmError

export_path, cache_path, token_limit = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
testapp_files = sys.argv[4:]
HERE = Path(__file__).parent
POOL = "full"

SYSTEM = (
    "Du bist Fachredakteur für kompendiale Texte (Lehrkräfte, WirLernenOnline). Du bekommst einen Baustein eines "
    "Kompendiums mit seiner Beschreibung und mehrere Absätze aus Quellartikeln. Bewerte jeden Absatz einzeln: Gehört er "
    "inhaltlich in genau diesen Baustein eines Kompendiums zum genannten Thema? 2 = gehört klar hinein, 1 = passt nur "
    "teilweise oder ist randständig, 0 = gehört nicht hinein (anderer Baustein, themenfremd oder inhaltsleer). Beachte "
    "die Abgrenzung des Bausteins. Antworte ausschließlich mit einem JSON-Objekt, das Absatz-IDs auf Bewertungen abbildet, "
    'zum Beispiel {"a1": 2, "a2": 0}.'
)


def text_hash(text: str) -> str:
    return hashlib.sha1(" ".join(text.split()).encode("utf-8")).hexdigest()[:16]


def slot_signature(slot: dict) -> str:
    raw = "|".join(str(slot.get(k)) for k in ("title", "description", "inclusions", "exclusions"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


export = json.load(open(export_path, encoding="utf-8"))
testapp: dict[str, dict] = {}
for path in testapp_files:
    for topic, pools in json.load(open(path, encoding="utf-8")).items():
        for pool, strategies in pools.items():
            testapp.setdefault(topic, {}).setdefault(pool, {}).update(strategies)

cache: dict[str, int] = json.load(open(cache_path, encoding="utf-8")) if cache_path.exists() else {}

# Seed from 2026-09-18 when its files are at hand: old key topic|slot|chunk_id -> text of that chunk in the old
# held-out corpus. Without them every pair is rated anew.
seed_files = [HERE / "mc_judge_cache.json", HERE / "mc_prepared_heldout.pkl", HERE / "mc_export.json"]
have_seed = all(path.exists() for path in seed_files)
old_cache = json.load(open(seed_files[0], encoding="utf-8")) if have_seed else {}
old_prepared = pickle.load(open(seed_files[1], "rb")) if have_seed else {}  # own file from 2026-09-18, trusted
old_signature = (
    {s["slot"]: slot_signature(s) for s in json.load(open(seed_files[2], encoding="utf-8"))["topics"][0]["slots"]}
    if have_seed
    else {}
)
seeded = 0
for key, rating in old_cache.items():
    topic, slot, chunk_id = key.split("|", 2)
    prepared = old_prepared.get(topic)
    if prepared is None:
        continue
    old_text = next((c.text for c in prepared.chunks if c.chunk_id == chunk_id), None)
    if old_text is None:
        continue
    new_key = f"{topic}|{slot}|{old_signature[slot]}|{text_hash(old_text)}"
    if new_key not in cache:
        cache[new_key] = rating
        seeded += 1
print(f"seeded from 2026-09-18: {seeded} ratings")

client = BApiClient(
    "https://b-api.staging.openeduhub.net", os.environ["B_API_KEY"], provider="openai", model="gpt-5.6-luna"
)
tokens = calls = 0
random.seed(7)
stopped = False

selections: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(lambda: defaultdict(dict))
for topic in export["topics"]:
    name = topic["topic"]
    chunk_by_id = {c["chunk_id"]: c for c in topic["chunks"]}
    slots = [s for s in topic["slots"] if not s.get("generator")]
    methods: dict[str, dict] = {f"MEIN {m}": run["selection"] for m, run in topic["mine"][POOL].items()}
    for strategy, runs in testapp.get(name, {}).get(POOL, {}).items():
        methods[f"TESTAPP {strategy}"] = runs["top2"]["selection"]
    for slot in slots:
        key, signature = slot["slot"], slot_signature(slot)
        wanted: list[str] = []
        for method, selection in methods.items():
            ids = [cid for cid, _ in selection.get(key, [])[:2]]
            selections[name][method][key] = [f"{name}|{key}|{signature}|{text_hash(chunk_by_id[c]['text'])}" for c in ids]
            wanted.extend(ids)
        unique = list(dict.fromkeys(wanted))
        by_hash = {text_hash(chunk_by_id[c]["text"]): c for c in unique}
        todo = [c for h, c in by_hash.items() if f"{name}|{key}|{signature}|{h}" not in cache]
        random.shuffle(todo)
        for start in range(0, len(todo), 8):
            if tokens >= token_limit:
                stopped = True
                break
            batch = todo[start : start + 8]
            alias = {f"a{i + 1}": cid for i, cid in enumerate(batch)}
            paragraphs = "\n\n".join(
                f"{a} (Artikel: {chunk_by_id[cid]['source_title']}; Abschnitt: {chunk_by_id[cid]['full_heading']}):\n"
                f"{' '.join(chunk_by_id[cid]['text'].split())[:900]}"
                for a, cid in alias.items()
            )
            user = (
                f"Thema des Kompendiums: {name}\nBaustein: {slot['title']}\nBeschreibung: {slot['description']}\n"
                f"Gehört hinein: {slot['inclusions']}\nAbgrenzung (gehört nicht hinein): {slot['exclusions']}\n\n"
                f"Absätze:\n{paragraphs}\n\nGib das JSON-Objekt zurück."
            )
            try:
                # 300 answer tokens as on 2026-09-18, plus the reasoning allowance the service itself adds (D33)
                result = client.chat(
                    [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                    max_output_tokens=client.completion_limit(300),
                )
            except LlmError as exc:
                print("judge call failed:", exc)
                continue
            tokens += result.total_tokens
            calls += 1
            text = result.text
            try:
                ratings = json.loads(text[text.find("{") : text.rfind("}") + 1])
            except ValueError:
                print("unparsable judge answer:", text[:120])
                continue
            for a, cid in alias.items():
                if isinstance(ratings.get(a), int) and ratings[a] in (0, 1, 2):
                    cache[f"{name}|{key}|{signature}|{text_hash(chunk_by_id[cid]['text'])}"] = ratings[a]
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"{name}: rated, calls so far {calls}, tokens so far {tokens}", flush=True)
    if stopped:
        print(f"STOPPED at the token limit {token_limit}")
        break

print(f"\njudge calls: {calls}, tokens: {tokens}, cached ratings: {len(cache)}")
totals: dict[str, list[int]] = defaultdict(list)
unrated: dict[str, int] = defaultdict(int)
covered: dict[str, int] = defaultdict(int)
good_slots: dict[str, int] = defaultdict(int)
for name, methods in selections.items():
    for method, by_slot in methods.items():
        for key, keys in by_slot.items():
            scores = [cache[k] for k in keys if k in cache]
            unrated[method] += len(keys) - len(scores)
            totals[method].extend(scores)
            covered[method] += bool(keys)
            good_slots[method] += any(s == 2 for s in scores)
n_topics = len(selections)
result_rows = []
print(f"\n{'Verfahren':36s} {'Absätze':>8s} {'Ø Note':>7s} {'klar %':>7s} {'teilw. %':>9s} {'falsch %':>9s} "
      f"{'belegt':>7s} {'Volltreffer':>12s} {'unbewertet':>11s}")
for method, scores in sorted(totals.items(), key=lambda kv: -sum(kv[1]) / max(len(kv[1]), 1)):
    n = max(len(scores), 1)
    row = {
        "method": method, "paragraphs": len(scores), "mean": sum(scores) / n,
        "clear": 100 * scores.count(2) / n, "partly": 100 * scores.count(1) / n, "wrong": 100 * scores.count(0) / n,
        "covered": covered[method] / n_topics, "full_hits": good_slots[method] / n_topics, "unrated": unrated[method],
    }
    result_rows.append(row)
    print(f"{method:36s} {len(scores):8d} {row['mean']:7.2f} {row['clear']:7.1f} {row['partly']:9.1f} {row['wrong']:9.1f} "
          f"{row['covered']:7.1f} {row['full_hits']:12.1f} {unrated[method]:11d}")
(cache_path.with_suffix(".result.json")).write_text(
    json.dumps({"topics": list(selections), "calls": calls, "tokens": tokens, "rows": result_rows}, ensure_ascii=False,
               indent=1),
    encoding="utf-8",
)
