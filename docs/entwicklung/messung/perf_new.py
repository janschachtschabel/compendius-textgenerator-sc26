"""Timing of the new compendium service: distinct topics after one warm-up call, rule-based only.

Every request switches the language model off explicitly (extraction and generation rule-based), so a server
with LLM defaults cannot spend b-api budget. Pass 1 asks each topic once, pass 2 repeats them (process caches),
pass 3 adds part 3 for collections with a known node id.

Usage: python perf_new.py <base-url> <out.json>
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.error
import urllib.request

BASE, OUT = sys.argv[1].rstrip("/"), sys.argv[2]
WARMUP = "Magnetismus"
TOPICS = [
    # the ten gold-standard topics
    "Barockliteratur", "Bruchrechnung", "Demokratie", "Französische Revolution", "Klimawandel",
    "Optik", "Photosynthese", "Programmiersprache", "Säure-Base-Konzepte", "Sinfonie",
    # the four held-out topics of the blind judge, and six further school topics
    "Plattentektonik", "Ökosystem", "Atommodell", "Industrielle Revolution",
    "Elektrischer Strom", "Wasserkreislauf", "Römisches Reich", "Lineare Funktion", "Zelle (Biologie)", "Gedicht",
]
COLLECTIONS = {
    "Optik": "9e7ae956-e9df-430f-bace-f3db4b910013",
    "Geometrische Optik": "f35c17d1-a29e-4b26-9d22-802682fad43d",
    "Photosynthese": "d38101c1-9a43-414b-a51f-e2dcff0add44",
}
RULES = {"extraction": "rule-based", "generation": "rule-based"}


def post(body: dict, timeout: int = 300) -> tuple[int, float, dict]:
    data = json.dumps({**body, **RULES}).encode("utf-8")
    request = urllib.request.Request(
        BASE + "/api/v2/compendium", data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    elapsed = time.perf_counter() - started
    try:
        return status, elapsed, json.loads(raw)
    except ValueError:
        return status, elapsed, {"raw": raw[:200].decode("utf-8", "replace")}


def record(label: str, body: dict) -> dict:
    status, elapsed, payload = post(body)
    audit = payload.get("audit") or {}
    row = {
        "label": label,
        "request": body,
        "http": status,
        "seconds": round(elapsed, 3),
        "timings_ms": audit.get("timings_ms"),
        "chunks_total": audit.get("chunks_total"),
        "chunks_assigned": audit.get("chunks_assigned"),
        "sections_filled": audit.get("sections_filled"),
        "sections_empty": audit.get("sections_empty"),
        "citations": audit.get("citations"),
        "sources": len(payload.get("sources") or []),
        "resolved_title": (payload.get("resolution") or {}).get("title"),
        "markdown_chars": len(payload.get("markdown") or ""),
        "parts_status": payload.get("parts_status"),
        "llm": audit.get("llm"),
        "error": None if status == 200 else payload.get("detail") or payload.get("raw"),
    }
    stages = " ".join(f"{k}={v}" for k, v in (row["timings_ms"] or {}).items())
    print(f"{label:9s} {body.get('topic') or body.get('collection_id'):28s} HTTP {status} {elapsed:6.2f} s  {stages}",
          flush=True)
    return row


def summary(rows: list[dict], label: str) -> None:
    ok = [r for r in rows if r["label"] == label and r["http"] == 200]
    if not ok:
        return
    seconds = sorted(r["seconds"] for r in ok)
    p90 = seconds[min(len(seconds) - 1, round(0.9 * (len(seconds) - 1)))]
    print(f"\n{label}: n={len(ok)}  median {statistics.median(seconds):.2f} s  p90 {p90:.2f} s  max {seconds[-1]:.2f} s")
    stages = sorted({k for r in ok for k in (r["timings_ms"] or {})})
    for stage in stages:
        values = [r["timings_ms"][stage] for r in ok if stage in (r["timings_ms"] or {})]
        print(f"  {stage:12s} median {statistics.median(values):7.0f} ms  max {max(values):7.0f} ms")


rows = [record("warmup", {"topic": WARMUP, "parts": ["world", "curricula"]})]
rows += [record("pass1", {"topic": t, "parts": ["world", "curricula"]}) for t in TOPICS]
rows += [record("pass2", {"topic": t, "parts": ["world", "curricula"]}) for t in TOPICS]
for name, node_id in COLLECTIONS.items():
    rows.append(record("all3", {"collection_id": node_id}))
    rows.append(record("part3", {"collection_id": node_id, "parts": ["collection"]}))

json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for label in ("pass1", "pass2", "all3", "part3"):
    summary(rows, label)
failed = [r for r in rows if r["http"] != 200]
print(f"\nfailed: {len(failed)}", [(r["request"], r["http"], str(r["error"])[:120]) for r in failed])
llm_used = [r for r in rows if r["llm"]]
print("llm used in any request:", bool(llm_used))
