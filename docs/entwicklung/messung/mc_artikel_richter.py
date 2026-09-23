"""Blind LLM judge for the article selection (project venv, gpt-5.6-luna via b-api): a second opinion on
eval/artikelwahl/korpus_labels.yaml.

Per topic one call rates every article of the pool (the corpus articles of the new service and the articles the old
service fetched) on the scale of the gold labels. The model sees the topic, the scale and per article only its title
and the beginning of its text, shuffled with a fixed seed, never which service chose it. A hard token limit stops
the run before the agreed budget; the key comes from B_API_KEY.

Usage: python mc_artikel_richter.py <pool.json> <out.json> <token_limit>
"""

from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.llm.client import BApiClient, LlmError

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

pool_path, out_path, token_limit = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
OPENING_CHARS = 180
PARALLEL = 4
SEED = 20260923

SYSTEM = (
    "Du beurteilst, welche Lexikonartikel in ein Kompendium für Lehrkräfte zu einem Unterrichtsthema gehören. "
    "Vergib je Artikel eine Note: 2 = gehört zum Thema (das Thema selbst, ein Teilgebiet, ein Kernbegriff, ein "
    "zentraler Vorgang, ein zentrales Ereignis oder eine Person, deren Bedeutung im Thema liegt); 1 = verwandt "
    "(Nachbarthema, direkter Oberbegriff, Hintergrund, einzelnes Werk als Beispiel, Person mit breiterem Wirken, "
    "allgemeiner Artikel zu einem beteiligten Stoff); 0 = passt nicht (andere Bedeutung, Begriffsklärung, Liste, "
    "Film gleichen Namens, weit entfernter Oberbegriff oder kein erkennbarer Bezug). Antworte ausschließlich mit "
    'einem JSON-Objekt, das jede Artikel-ID auf ihre Note abbildet, zum Beispiel {"a1": 2, "a2": 0}.'
)

pool = json.loads(pool_path.read_text(encoding="utf-8"))
client = BApiClient(
    "https://b-api.staging.openeduhub.net", os.environ["B_API_KEY"], provider="openai", model="gpt-5.6-luna",
    max_concurrency=PARALLEL,
)
lock = threading.Lock()
spent = {"tokens": 0, "calls": 0, "failed": 0, "stopped": False}


def rate(topic: str) -> dict:
    keys = sorted(pool[topic])
    random.Random(f"{SEED}:{topic}").shuffle(keys)
    alias = {f"a{i + 1}": key for i, key in enumerate(keys)}
    listing = "\n".join(
        f"{a}: {key.split(':', 1)[1]} — {pool[topic][key][:OPENING_CHARS]}" for a, key in alias.items()
    )
    user = f"Thema des Kompendiums: {topic}\n\nArtikel:\n{listing}\n\nGib das JSON-Objekt zurück."
    with lock:
        if spent["tokens"] >= token_limit:
            spent["stopped"] = True
            return {"topic": topic, "skipped": True}
    started = time.perf_counter()
    try:
        result = client.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            max_output_tokens=client.completion_limit(12 * len(keys)),
        )
    except LlmError as exc:
        with lock:
            spent["failed"] += 1
        return {"topic": topic, "error": str(exc)[:200]}
    with lock:
        spent["tokens"] += result.total_tokens
        spent["calls"] += 1
    text = result.text
    try:
        parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except ValueError:
        parsed = {}
    notes = {}
    for a, key in alias.items():
        value = parsed.get(a)
        if isinstance(value, (int, float)) and value in (0, 1, 2):
            notes[key] = int(value)
    return {"topic": topic, "notes": notes, "articles": len(keys), "seconds": round(time.perf_counter() - started, 2),
            "tokens": result.total_tokens, "finish_reason": result.finish_reason}


with ThreadPoolExecutor(max_workers=PARALLEL) as executor:
    results = list(executor.map(rate, list(pool)))
out_path.write_text(json.dumps({"spent": spent, "topics": results}, ensure_ascii=False, indent=1), encoding="utf-8")
rated = sum(len(r.get("notes", {})) for r in results)
print(f"Aufrufe {spent['calls']}, fehlgeschlagen {spent['failed']}, Tokens {spent['tokens']}, "
      f"bewertet {rated} von {sum(len(v) for v in pool.values())}, gestoppt {spent['stopped']}")
