"""Messskript M75, Probe zur Haltezeit des Prompt-Caches (08.10.2026): trifft der Cache nach einer Pause noch, und hilft
die verlängerte Haltezeit, die OpenAI anbietet (``prompt_cache_retention: "24h"``)?

Zwei gemeinsame Texte von je rund 3.600 Tokens als System-Nachricht (wie der Bausteinkatalog der Zuordnung), jeder mit
einer Kennung, die kein früherer Aufruf geschickt hat: einer mit, einer ohne verlängerte Haltezeit. Je Text ein Aufruf
sofort, einer nach 20 und einer nach 60 Minuten; gezählt werden die Eingabe-Tokens aus dem Cache. Über OpenAI direkt
(OPENAI_API_KEY), nicht über die b-api: ob die b-api den Parameter durchreicht, ist eine eigene Frage. Der Schlüssel
wird nie ausgegeben.

Usage: python mc_cache_dauer.py <out.json> [<minuten>,<minuten>]
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-6-luna"


def shared_text() -> str:
    """About 3,600 tokens, opened by an id no earlier call has sent."""
    return f"Lauf {uuid.uuid4().hex[:8]}. " + " ".join(
        f"Baustein {i}: Schreibe sachlich, ohne Floskeln, mit Belegnummern wo vorhanden, und bleibe beim Thema des "
        f"Kompendiums; erfinde keine Namen, Zahlen oder Fundstellen, die du nicht sicher kennst."
        for i in range(1, 70)
    )


def ask(client: httpx.Client, system: str, question: str, retention: bool) -> dict:
    body: dict = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
        "max_completion_tokens": 200,
        "reasoning_effort": "none",
    }
    if retention:
        body["prompt_cache_retention"] = "24h"
    started = time.monotonic()
    response = client.post(URL, json=body)
    row: dict = {"retention": retention, "status": response.status_code, "s": round(time.monotonic() - started, 2)}
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200:
        row["error"] = str((data.get("error") or {}).get("message") or response.text[:200])
        return row
    usage = data.get("usage") or {}
    row.update(prompt=usage.get("prompt_tokens"), cached=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
    return row


def main() -> None:
    out = Path(sys.argv[1])
    pauses = [int(m) for m in (sys.argv[2] if len(sys.argv) > 2 else "20,60").split(",")]
    texts = {True: shared_text(), False: shared_text()}
    rows: list[dict] = []
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        start = time.monotonic()
        for at in [0, *pauses]:
            wait = start + at * 60 - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            for retention, system in texts.items():
                row = ask(client, system, f"Nenne in einem Satz den Zweck von Baustein {at % 69 + 1}.", retention)
                rows.append({"minute": at, **row})
                print(f"# {at} min, 24h={retention}: {row}", file=sys.stderr, flush=True)
                out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
