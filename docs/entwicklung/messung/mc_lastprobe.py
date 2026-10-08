"""Messskript M81a (08.10.2026, Audit vom 18.09., „Thread-Sicherheit von libzim“): der Dienst unter paralleler Last.

Ein ``libzim.Archive`` je Archiv wird von allen Threads eines Workers zugleich gelesen. Das Audit verlangte einen
Lasttest mit 20 parallelen Anfragen gegen den echten Dump. Das Skript stellt jedes Thema einmal nacheinander, dann
zweimal mit ``<parallel>`` Anfragen zugleich, jeweils als ``llm-free`` (ohne LLM, also deterministisch), und vergleicht
jeden Text mit dem aus dem Lauf nacheinander; nur die Zeile ``generated_at`` darf sich unterscheiden. Ein 429 wird nach
``Retry-After`` wiederholt und gezählt.

Gegen den Entwicklungscontainer, aus der venv dieses Projekts:

  python docs/entwicklung/messung/mc_lastprobe.py <themen.json> <out.json> [<basis-url>] [<parallel>]

Danach im Log des Containers nach Fehlern und mit ``docker inspect`` nach Neustarts sehen. Ergebnis ohne die Texte:
je Durchgang Zeiten und Status, je Thema Sekunden und ob der Text gleich war.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

topics: list[str] = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out_path = Path(sys.argv[2])
base = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8001"
parallel = int(sys.argv[4]) if len(sys.argv) > 4 else 20
client = httpx.Client(base_url=base, timeout=900.0)
GENERATED_AT = re.compile(r"(?m)^generated_at: .*$")


def ask(topic: str) -> dict[str, Any]:
    body = json.dumps({"topic": topic, "preset": "llm-free"}, ensure_ascii=False).encode("utf-8")
    retried = 0
    while True:
        started = time.monotonic()
        try:
            response = client.post("/api/v2/compendium", content=body, headers={"Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            return {"status": None, "error": f"{type(exc).__name__}: {exc}", "seconds": time.monotonic() - started}
        if response.status_code == 429 and retried < 20:
            retried += 1
            time.sleep(float(response.headers.get("Retry-After", "5")))
            continue
        row: dict[str, Any] = {
            "status": response.status_code,
            "seconds": round(time.monotonic() - started, 2),
            "retried_429": retried,
        }
        if response.status_code == 200:
            row["text"] = GENERATED_AT.sub("", response.json().get("markdown") or "")
        return row


def run(workers: int) -> dict[str, Any]:
    started = time.monotonic()
    if workers == 1:
        rows = {topic: ask(topic) for topic in topics}
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            rows = dict(zip(topics, pool.map(ask, topics), strict=True))
    return {"seconds": round(time.monotonic() - started, 1), "rows": rows}


phases = {"nacheinander": run(1), "parallel_1": run(parallel), "parallel_2": run(parallel)}
reference = phases["nacheinander"]["rows"]
summary: dict[str, Any] = {"basis": base, "parallel": parallel, "themen": len(topics), "durchgaenge": {}}
for name, phase in phases.items():
    rows = phase["rows"]
    statuses: dict[str, int] = {}
    for row in rows.values():
        statuses[str(row["status"])] = statuses.get(str(row["status"]), 0) + 1
    seconds = [row["seconds"] for row in rows.values()]
    summary["durchgaenge"][name] = {
        "sekunden": phase["seconds"],
        "status": statuses,
        "je_anfrage_median_s": statistics.median(seconds),
        "je_anfrage_max_s": max(seconds),
        "wiederholt_429": sum(row.get("retried_429", 0) for row in rows.values()),
        "texte_anders": [topic for topic, row in rows.items() if row.get("text") != reference[topic].get("text")],
    }
    print(name, json.dumps({k: v for k, v in summary["durchgaenge"][name].items()}, ensure_ascii=False), file=sys.stderr)
out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
