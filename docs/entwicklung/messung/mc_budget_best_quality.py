"""D59 on the widest topic of M32 (M33): which budget lets best-quality check every curriculum element of part 2?

In M32 the LLM check of "Demokratie" without a subject (819 elements) ran out of the 60,000 tokens of a request and
left 180 elements to the rules. D59 gives the two best-quality profiles a budget of their own per request. This asks
the same topic in the flow of the service, through the API, with the budget given on the command line:

- compendium: POST /api/v2/compendium with parts world and curricula, once per best-quality profile - part 1 with the
  LLM assigning the paragraphs (and in best-quality-generated writing the blocks), then part 2 with the check, all
  from one budget;
- search (with --search): GET /api/v2/lehrplan/search with mode topic and preset best-quality - the article chosen as
  for part 2, every hit checked.

Each run is appended to the output file with its budget: per request the seconds, the tokens and calls, and from the
audit how many elements the model rated and answered, dropped, and left to the rules and why; no texts. B_API_KEY
from .env, never printed. The b-api answers a prompt it has seen before from its cache (same answer and usage, a
fraction of the time), so the seconds of batches asked before are too short; tokens and counts are not affected.

Usage (project venv, from the project root; lehrplan.db in STATE_DIR, the archives of kompendium-test):
python docs/entwicklung/messung/mc_budget_best_quality.py <out.json> <budget> [--search]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
TOPIC = "Demokratie"
PROFILES = ("best-quality", "best-quality-generated")


def configure(budget: int) -> None:
    # over the .env: the LLM of the staging b-api, the budget under test, the archives of kompendium-test, no rate
    # limit for one caller
    os.environ["LLM_ENABLED"] = "true"
    os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
    os.environ["LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY"] = str(budget)
    os.environ["ZIM_PATHS"] = ",".join(ZIMS)
    os.environ["RATE_LIMIT"] = "0"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")


def check_block(block: dict[str, Any] | None) -> dict[str, Any] | None:
    if block is None:
        return None
    keys = ("requested", "used", "rated", "answered", "dropped", "fallbacks", "fallback")
    return {key: block.get(key) for key in keys}


def compendium(client: Any, profile: str) -> dict[str, Any]:
    started = time.perf_counter()
    response = client.post(
        "/api/v2/compendium", json={"topic": TOPIC, "parts": ["world", "curricula"], "preset": profile}
    )
    seconds = round(time.perf_counter() - started, 1)
    body = response.json()
    audit = body["audit"]
    llm = audit.get("llm") or {}
    matching = llm.get("matching") or {}
    generation = llm.get("generation") or {}
    summary = (body.get("curricula") or {}).get("summary") or {}
    return {
        "status": response.status_code,
        "seconds": seconds,
        "timings_ms": {key: audit["timings_ms"].get(key) for key in ("match", "synthesize", "curricula")},
        "tokens": audit.get("llm_tokens"),
        "matching": {key: matching.get(key) for key in ("paragraphs", "answered", "fallback_paragraphs", "fallbacks")},
        "generation": {key: generation.get(key) for key in ("used", "sections", "fallbacks")},
        "curriculum_check": check_block(llm.get("curriculum_check")),
        "part_2": {key: summary.get(key) for key in ("matches", "bundled")},
    }


def search(client: Any) -> dict[str, Any]:
    started = time.perf_counter()
    params = {"q": TOPIC, "mode": "topic", "preset": "best-quality", "limit": 500}
    response = client.get("/api/v2/lehrplan/search", params=params)
    seconds = round(time.perf_counter() - started, 1)
    body = response.json()
    llm = body.get("llm") or {}
    return {
        "status": response.status_code,
        "seconds": seconds,
        "total_hits": body.get("total_hits"),
        "returned": len(body.get("matches", [])),
        "tokens": body.get("llm_tokens"),
        "curriculum_check": check_block(llm.get("curriculum_check")),
        "article_choice": {key: (llm.get("article_choice") or {}).get(key) for key in ("requested", "used", "asked")},
    }


def main(out: Path, budget: int, with_search: bool) -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    configure(budget)
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import get_settings

    settings = get_settings()
    with TestClient(create_app(settings)) as client:
        run: dict[str, Any] = {
            "budget_best_quality": settings.llm_max_tokens_per_request_best_quality,
            "compendium": {profile: compendium(client, profile) for profile in PROFILES},
        }
        if with_search:
            run["search"] = search(client)
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"topic": TOPIC, "runs": []}
    results["runs"].append(run)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(run, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]), "--search" in sys.argv[3:])
