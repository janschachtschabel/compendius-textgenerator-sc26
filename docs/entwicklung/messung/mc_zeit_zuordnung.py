"""Time of matcher=llm against the default strategy on whole compendia (project venv, b-api, gpt-5.6-luna).

Five plain topics no earlier measurement asked, so no batch comes out of the b-api's cache. Each runs through
CompendiumService.generate with part 1 only, Model2Vec on and the article choice of the rules, once with hybrid_light
and once with matcher=llm, the two in turns per topic; a first pass with hybrid_light warms archives and model.

Usage: python mc_zeit_zuordnung.py <out.json>
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TOPICS = ["Evolution", "Reformation", "Nervensystem", "Kernspaltung", "Impressionismus"]
WAYS = ["hybrid_light", "llm"]

out_path = Path(sys.argv[1])
service = cli_service(ZIMS)
service.settings.model2vec_path = M2V
assert service.llm is not None, "LLM_ENABLED did not reach the settings"


def request(topic: str, matcher: str) -> GenerateRequest:
    return GenerateRequest(topic=topic, parts=["world"], matcher=matcher, article_choice="rule-based")


for topic in TOPICS:
    service.generate(request(topic, "hybrid_light"))

rows: list[dict] = []
for index, topic in enumerate(TOPICS):
    for way in WAYS if index % 2 == 0 else list(reversed(WAYS)):
        started = time.perf_counter()
        result = service.generate(request(topic, way))
        seconds = time.perf_counter() - started
        matching = (result.audit.llm or {}).get("matching") or {}
        rows.append({
            "thema": topic, "weg": way, "sekunden": round(seconds, 2), "phasen_ms": dict(result.audit.timings_ms),
            "tokens": (result.audit.llm_tokens or {}).get("total", 0), "absaetze": matching.get("paragraphs", 0),
            "rueckfall": matching.get("fallback_paragraphs", 0), "zugeordnet": result.audit.matcher,
        })
        print(f"{way:12s} {seconds:6.2f} s  {topic}", flush=True)

summary: dict[str, dict] = {}
for way in WAYS:
    done = [r for r in rows if r["weg"] == way]
    summary[way] = {
        "median_s": round(statistics.median(r["sekunden"] for r in done), 2),
        "median_zuordnung_s": round(statistics.median(r["phasen_ms"]["match"] / 1000 for r in done), 2),
        "max_s": max(r["sekunden"] for r in done), "tokens": sum(r["tokens"] for r in done),
        "absaetze": sum(r["absaetze"] for r in done), "rueckfall": sum(r["rueckfall"] for r in done),
    }
    print(way, summary[way])
out_path.write_text(json.dumps({"zusammenfassung": summary, "laeufe": rows}, ensure_ascii=False, indent=1), "utf-8")
