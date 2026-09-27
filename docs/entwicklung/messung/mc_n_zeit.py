"""M39: time and tokens of balanced with the question N (D63), on topics no measurement asked before.

The b-api answers a prompt it has seen from its cache in 0.1 to 0.3 s, so N is timed on ten topics none of M1 to M39
sent: the question N and the choice of an unsure article reach the model for the first time. As M27b: part 1 and
part 2, LLM_MAX_TOKENS_PER_REQUEST 100 000, llm-free first on every topic (it sends no prompt and warms the archive).

Usage (project venv, from the project root): python docs/entwicklung/messung/mc_n_zeit.py <out.json> --m2v <model dir>
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ["LLM_MAX_TOKENS_PER_REQUEST"] = "100000"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
TOPICS = [
    "Kontinentaldrift", "Zellteilung", "Reformation", "Satz des Pythagoras", "Wasserkreislauf",
    "Stromkreis", "Expressionismus", "Kalter Krieg", "Ökosystem", "Säuren und Basen",
]  # fmt: skip
PARTS = ["world", "curricula"]

out_path = Path(sys.argv[1])
service = cli_service(ZIMS)
service.settings.model2vec_path = sys.argv[sys.argv.index("--m2v") + 1]
if service.llm is None:
    raise SystemExit("LLM_ENABLED did not reach the settings")


def run(topic: str, profile: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = service.generate(GenerateRequest(topic=topic, preset=profile, parts=PARTS))  # type: ignore[arg-type]
    seconds = time.perf_counter() - started
    choice = (result.audit.llm or {}).get("article_choice") or {}
    return {
        "hauptartikel": result.resolution.title,
        "sekunden": round(seconds, 2),
        "phasen_ms": result.audit.timings_ms,
        "tokens": (result.audit.llm_tokens or {}).get("total", 0),
        "aufrufe": (result.audit.llm_tokens or {}).get("calls", 0),
        "n_gefunden": len(choice.get("articles_found") or []),
        "n_rueckfall": choice.get("articles_fallback"),
        "artikelwahl_gefragt": choice.get("asked"),
    }


rows = []
for topic in TOPICS:
    free, balanced = run(topic, "llm-free"), run(topic, "balanced")
    rows.append({"thema": topic, "llm-free": free, "balanced": balanced})
    print(f"{topic:24s} llm-free {free['sekunden']:5.2f} s | balanced {balanced['sekunden']:5.2f} s, "
          f"{balanced['tokens']} Tokens, N {balanced['n_gefunden']} Artikel", flush=True)  # fmt: skip

summary = {
    profile: {
        "sekunden_median": statistics.median(r[profile]["sekunden"] for r in rows),
        "sekunden_max": max(r[profile]["sekunden"] for r in rows),
        "tokens_median": statistics.median(r[profile]["tokens"] for r in rows),
        "resolve_ms_median": statistics.median(r[profile]["phasen_ms"].get("resolve", 0) for r in rows),
    }
    for profile in ("llm-free", "balanced")
}
print(json.dumps(summary, ensure_ascii=False))
out_path.write_text(json.dumps({"zusammenfassung": summary, "themen": rows}, ensure_ascii=False, indent=1),
                    encoding="utf-8")  # fmt: skip
