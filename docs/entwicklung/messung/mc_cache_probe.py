"""M46: where must the opening the calls share stand for the b-api to read it from its prompt cache, and must one
call go ahead of the others?

Layouts, each with a text of its own the cache cannot hold yet, two calls one after the other:
  S  the shared text is the system message, the user message differs
  U  a short system message; the user message opens with the shared text and ends differently (as matcher=llm and
     the writers were built until D69)
Head start, the shared text as system message: one call, then three together after 0, 1 and 2 seconds.

The key comes from B_API_KEY. About 7,000 prompt tokens per layout and 14,500 per head start, a few dozen out.

Usage: python mc_cache_probe.py <out.json>
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx

BASE = "https://b-api.staging.openeduhub.net/api/v1/llm/openai/chat/completions"
KEY = os.environ["B_API_KEY"]
MODEL = "gpt-6-luna"
SHORT_SYSTEM = "Du ordnest Absätze den Bausteinen eines Kompendiums zu. Antworte knapp."


def shared_text() -> str:
    """About 3,600 tokens, opened by a run id no earlier call has sent."""
    return f"Lauf {uuid.uuid4().hex[:8]}. " + " ".join(
        f"Baustein {i}: Schreibe sachlich, ohne Floskeln, mit Belegnummern wo vorhanden, und bleibe beim Thema des "
        f"Kompendiums; erfinde keine Namen, Zahlen oder Fundstellen, die du nicht sicher kennst."
        for i in range(1, 70)
    )


def call(messages: list[dict[str, str]]) -> dict[str, object]:
    body = {"model": MODEL, "messages": messages, "max_completion_tokens": 400, "reasoning_effort": "low"}
    started = time.monotonic()
    response = httpx.post(BASE, headers={"X-API-KEY": KEY, "Accept": "application/json"}, json=body, timeout=120)
    usage = response.json().get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return {
        "status": response.status_code,
        "seconds": round(time.monotonic() - started, 1),
        "prompt_tokens": usage.get("prompt_tokens"),
        "cached_tokens": details.get("cached_tokens"),
        "cache_write_tokens": details.get("cache_write_tokens"),
    }


def layouts() -> dict[str, list[dict[str, object]]]:
    found: dict[str, list[dict[str, object]]] = {}
    for layout in ("S", "U"):
        text, found[layout] = shared_text(), []
        for tail in ("Thema: Photosynthese. Schreibe zwei Sätze.", "Thema: Photosynthese. Nenne drei Begriffe."):
            if layout == "S":
                messages = [{"role": "system", "content": text}, {"role": "user", "content": tail}]
            else:
                messages = [{"role": "system", "content": SHORT_SYSTEM}, {"role": "user", "content": f"{text}\n\n{tail}"}]
            found[layout].append(call(messages))
    return found


def head_starts() -> dict[str, list[dict[str, object]]]:
    found: dict[str, list[dict[str, object]]] = {}
    for seconds in (0.0, 1.0, 2.0):
        system, results = shared_text(), []

        def ask(tail: str, label: str, system: str = system, results: list = results) -> None:
            answer = call([{"role": "system", "content": system}, {"role": "user", "content": tail}])
            results.append({"call": label, **answer})

        first = threading.Thread(target=ask, args=("Thema: Optik. Zwei Sätze.", "first"))
        first.start()
        time.sleep(seconds)
        rest = [threading.Thread(target=ask, args=(f"Thema: Optik, Teil {n}. Zwei Sätze.", f"after_{n}")) for n in (1, 2, 3)]
        for thread in rest:
            thread.start()
        for thread in [first, *rest]:
            thread.join()
        found[f"{seconds:.0f}s"] = sorted(results, key=lambda result: str(result["call"]))
    return found


if __name__ == "__main__":
    out = {"model": MODEL, "layouts": layouts(), "head_starts": head_starts()}
    Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
