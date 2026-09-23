"""LLM as a reference matcher (gpt-5.6-luna via b-api): assign every paragraph to one content block or none.

Runs on the gold pool (the labelled paragraphs of the ten gold topics). The model gets what a human labeller got:
the block definitions of the sc26 template (including what does NOT belong) and the labelling rules of the gold
standard (eval/README.md). Per paragraph it sees the article, its role, the heading path and the text (cut to 700
characters) and answers with a block key or "keiner" plus a confidence. Batches of 25, four calls in parallel per
topic; latency, tokens and wall time are recorded. A hard token limit stops the run before the agreed budget.

The result is written into a copy of the export as topic["mine"]["gold"]["LLM gpt-5.6-luna"] (classified +
selection by confidence), so mc_eval.py measures it exactly like every other method.

Usage (project venv): python mc_llm_matcher.py <export.json> <out_export.json> <raw.json> <token_limit>
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.llm.client import BApiClient, LlmError

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

export_path, out_path, raw_path, token_limit = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4])
LABEL = "LLM gpt-5.6-luna"
BATCH = 25
PARALLEL = 4
TEXT_CHARS = 700

RULES = """Regeln der Zuordnung:
- themendefinition nur für die Einleitung des Hauptartikels, ausdrückliche Definitions- und Abgrenzungsabsätze des
  Themas und die Einleitung desselben Themas aus Klexikon.
- systematik: Teilgebiete, Typen und Varianten des Themas, Einleitungen von Teilgebiets-Artikeln, Gliederungen und
  Typologien.
- fachinhalte: Gesetze, Mechanismen, Begriffe, Rechenregeln, Verlauf eines historischen Ereignisses (bei
  Ereignisthemen), Theorien; der Regelfall für Fließtext des Hauptartikels.
- gesellschaftlicher_kontext: Bedeutung, Alltag, Kritik, Rezeption, Debatten, Politik, Risiken.
- entwicklung_ausblick: Geschichte des Themas, Forschungsgeschichte, Epochen, Folgen, Prognosen.
- beruf_wirtschaft, bildung, regularien, praxis, querschnitt gemäß ihren Beschreibungen.
- keiner: Personen-, Werk- und Autorenlisten, Formelreste, Bildunterschriften, Verweise, Biografie- und
  Einzelwerk-Absätze, Filmartikel, Listenartikel, Absätze ohne Themenbezug."""

SYSTEM = (
    "Du ordnest Absätze aus Lexikonartikeln den Bausteinen eines Kompendiums für Lehrkräfte zu (WirLernenOnline). "
    "Jeder Absatz gehört in genau einen Baustein oder in keinen. Antworte ausschließlich mit einem JSON-Objekt, das "
    'jede Absatz-ID auf [Baustein-Schlüssel oder "keiner", Sicherheit von 0 bis 1] abbildet, zum Beispiel '
    '{"p1": ["fachinhalte", 0.8], "p2": ["keiner", 0.9]}.'
)

export = json.load(open(export_path, encoding="utf-8"))
client = BApiClient(
    "https://b-api.staging.openeduhub.net", os.environ["B_API_KEY"], provider="openai", model="gpt-5.6-luna",
    max_concurrency=PARALLEL,
)
lock = threading.Lock()
spent = {"tokens": 0, "calls": 0, "failed": 0, "stopped": False}


def block_text(slots: list[dict]) -> str:
    return "\n".join(
        f"- {s['slot']} ({s['title']}): {s['description']} Gehört hinein: {s['inclusions']} "
        f"Gehört nicht hinein: {s['exclusions']}"
        for s in slots
    )


def role(chunk: dict) -> str:
    if chunk["source_is_primary"]:
        return "Hauptartikel"
    if chunk["source_origin"] == "same_topic":
        return f"dasselbe Thema aus {chunk['source_project']}"
    return "weiterer Artikel"


def ask(topic: str, blocks: str, batch: list[dict]) -> tuple[dict, dict]:
    alias = {f"p{i + 1}": c for i, c in enumerate(batch)}
    paragraphs = "\n\n".join(
        f"{a} (Artikel: {c['source_title']}, {role(c)}; Abschnitt: {c['full_heading']}):\n"
        f"{' '.join(c['text'].split())[:TEXT_CHARS]}"
        for a, c in alias.items()
    )
    user = f"Thema des Kompendiums: {topic}\n\nBausteine:\n{blocks}\n\n{RULES}\n\nAbsätze:\n{paragraphs}\n\nGib das JSON-Objekt zurück."
    with lock:
        if spent["tokens"] >= token_limit:
            spent["stopped"] = True
            return {}, {"skipped": True}
    started = time.perf_counter()
    try:
        result = client.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            max_output_tokens=client.completion_limit(40 * len(batch)),
        )
    except LlmError as exc:
        with lock:
            spent["failed"] += 1
        return {}, {"error": str(exc)[:200], "seconds": round(time.perf_counter() - started, 2)}
    seconds = round(time.perf_counter() - started, 2)
    with lock:
        spent["tokens"] += result.total_tokens
        spent["calls"] += 1
    text = result.text
    try:
        parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except ValueError:
        parsed = {}
    answers = {}
    for a, c in alias.items():
        value = parsed.get(a)
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
            try:
                answers[c["chunk_id"]] = [value[0].strip().lower(), float(value[1])]
            except (TypeError, ValueError):
                continue
    meta = {"seconds": seconds, "tokens": result.total_tokens, "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens, "paragraphs": len(batch), "answered": len(answers),
            "finish_reason": result.finish_reason}
    return answers, meta


raw: dict[str, dict] = {}
for topic in export["topics"]:
    name = topic["topic"]
    slots = [s for s in topic["slots"] if not s.get("generator")]
    keys = {s["slot"] for s in slots}
    blocks = block_text(slots)
    pool = [c for c in topic["chunks"] if c["chunk_id"] in topic["gold"]]
    batches = [pool[i : i + BATCH] for i in range(0, len(pool), BATCH)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=PARALLEL) as executor:
        results = list(executor.map(lambda b: ask(name, blocks, b), batches))
    wall = round(time.perf_counter() - started, 2)
    answers: dict[str, list] = {}
    calls = []
    for batch_answers, meta in results:
        answers.update(batch_answers)
        calls.append(meta)
    classified = {cid: slot for cid, (slot, _conf) in answers.items() if slot in keys}
    selection: dict[str, list] = {}
    for cid, (slot, conf) in answers.items():
        if slot in keys:
            selection.setdefault(slot, []).append([cid, conf])
    for slot in selection:
        selection[slot].sort(key=lambda item: -item[1])
    unknown = sum(1 for slot, _ in answers.values() if slot not in keys and slot != "keiner")
    topic["mine"]["gold"][LABEL] = {"ms": int(wall * 1000), "classified": classified, "selection": selection}
    raw[name] = {"paragraphs": len(pool), "answered": len(answers), "unknown_keys": unknown, "wall_seconds": wall,
                 "calls": calls, "answers": answers}
    print(f"{name:24s} Absätze {len(pool):3d} beantwortet {len(answers):3d} Aufrufe {len(batches)} "
          f"Wand {wall:5.1f} s  Tokens bisher {spent['tokens']}", flush=True)
    if spent["stopped"]:
        print(f"STOPPED at the token limit {token_limit}")
        break

out_path.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
raw_path.write_text(json.dumps({"spent": spent, "topics": raw}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\ncalls {spent['calls']}, failed {spent['failed']}, tokens {spent['tokens']}")
