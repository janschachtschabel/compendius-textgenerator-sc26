"""Measure the OLD compendium service (alterCode/compendious v0.2.0) unchanged: pipeline-compendium-only per topic.

The service code is not touched. Two library calls are wrapped for measurement only: every chat completion
(duration, usage, parameters) and every HTTP request aiohttp sends (URL, looked-up titles, status, duration).
Run with the old service's venv and cwd = alterCode/compendious; all topics share one event loop because the old
Wikipedia client keeps its aiohttp session between calls.

Env: B_API_KEY (inherited, never written out), B_API_BASE_URL, B_API_MODEL.
Usage: python old_run.py <out_dir> <topic> [<topic> ...]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp
import openai.resources.chat.completions as chat_completions

sys.path.insert(0, os.getcwd())
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(sys.argv[1])
TOPICS = sys.argv[2:]
KEY = os.environ.get("B_API_KEY", "").strip()
llm_calls: list[dict] = []
http_calls: list[dict] = []


def clean(text: str) -> str:
    return text.replace(KEY, "***") if KEY else text


def purpose(messages: list[dict] | None) -> str:
    system = next((m.get("content", "") for m in messages or [] if m.get("role") == "system"), "")
    user = next((m.get("content", "") for m in messages or [] if m.get("role") == "user"), "")
    return clean(" ".join(str(system or user).split())[:90])


_create = chat_completions.Completions.create


def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    record = {
        "model": kwargs.get("model"),
        "max_tokens": kwargs.get("max_tokens"),
        "temperature": kwargs.get("temperature"),
        "purpose": purpose(kwargs.get("messages")),
        "prompt_chars": sum(len(str(m.get("content", ""))) for m in kwargs.get("messages") or []),
    }
    started = time.perf_counter()
    try:
        response = _create(self, *args, **kwargs)
    except Exception as exc:
        record.update(seconds=round(time.perf_counter() - started, 2), error=clean(f"{type(exc).__name__}: {exc}")[:300])
        llm_calls.append(record)
        raise
    usage = response.usage
    record.update(
        seconds=round(time.perf_counter() - started, 2),
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
        finish_reason=response.choices[0].finish_reason if response.choices else None,
        answer_chars=len(response.choices[0].message.content or "") if response.choices else 0,
    )
    llm_calls.append(record)
    return response


chat_completions.Completions.create = create

_request = aiohttp.ClientSession._request


async def request(self, method, str_or_url, **kwargs):  # type: ignore[no-untyped-def]
    params = kwargs.get("params") or {}
    record = {
        "method": method,
        "url": clean(str(str_or_url))[:160],
        "titles": params.get("titles") if isinstance(params, dict) else None,
    }
    started = time.perf_counter()
    try:
        response = await _request(self, method, str_or_url, **kwargs)
    except Exception as exc:
        record.update(seconds=round(time.perf_counter() - started, 2), error=clean(f"{type(exc).__name__}: {exc}")[:200])
        http_calls.append(record)
        raise
    record.update(seconds=round(time.perf_counter() - started, 2), status=response.status)
    http_calls.append(record)
    return response


aiohttp.ClientSession._request = request

from app.api.v1.pipeline_compendium_only import (  # noqa: E402
    PipelineCompendiumOnlyRequest,
    pipeline_compendium_only_endpoint,
)
from app.core.settings import settings  # noqa: E402


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"model {settings.B_API_MODEL} at {settings.B_API_BASE_URL}", flush=True)
    for topic in TOPICS:
        llm_calls.clear()
        http_calls.clear()
        started = time.perf_counter()
        result, error = None, None
        try:
            response = await pipeline_compendium_only_endpoint(PipelineCompendiumOnlyRequest(text=topic))
            result = response.model_dump()
        except Exception as exc:  # the measurement records failures instead of stopping
            error = clean(f"{type(exc).__name__}: {exc}")[:400]
        seconds = round(time.perf_counter() - started, 2)
        record = {
            "topic": topic,
            "seconds": seconds,
            "error": error,
            "model": settings.B_API_MODEL,
            "base_url": settings.B_API_BASE_URL,
            "result": result,
            "llm_calls": list(llm_calls),
            "http_calls": list(http_calls),
        }
        (OUT / f"{topic}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        entities = (result or {}).get("linker_output", {}).get("entities", [])
        found = sum(1 for e in entities if e["sources"]["wikipedia"]["status"] == "found")
        markdown = (result or {}).get("compendium_output", {}).get("markdown", "")
        statuses: dict[str, int] = {}
        for call in http_calls:
            key = str(call.get("status", call.get("error", "?")))[:20]
            statuses[key] = statuses.get(key, 0) + 1
        tokens = sum(c.get("total_tokens") or 0 for c in llm_calls)
        print(
            f"{topic:26s} {seconds:6.1f} s  LLM {len(llm_calls)} Aufrufe {tokens} Tokens  "
            f"Wikipedia {len(http_calls)} Anfragen {statuses}  Entitäten {found}/{len(entities)} gefunden  "
            f"Markdown {len(markdown)} Zeichen  {'FEHLER ' + error if error else ''}",
            flush=True,
        )


asyncio.run(main())
