"""Time of article_choice=llm against the previous standard (project venv; b-api, gpt-5.6-luna, for the llm way).

Topics no earlier measurement asked, so no prompt comes out of the b-api's cache, which answers a prompt it has seen
in 0.1 to 0.3 s: 20 plain school topics, 9 ambiguous words with a subject and a genitive phrase. Each runs through
CompendiumService.generate with part 1 only, Model2Vec on. Before the timed pass every topic runs once with the rules,
so archive files and the model are warm and no prompt reaches the b-api early. The code on PYTHONPATH decides the
version: the previous standard (a git archive of c03dafe, which knows no article_choice) or the current one, where
the ways take turns per topic.

M25 measured the current code again after the hit check came to cover the linked sub-articles: --m25 takes 30 other
topics no measurement had asked before (the first 30 ran in M13 and could come out of the cache), --m2v the path of
the Model2Vec model when the hub has no copy.

Usage: python mc_zeit_artikelwahl.py <out.json> <way>... [--m25] [--m2v <path>]   (ways: rule-based, llm)
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

WAYS = [arg for arg in sys.argv[2:] if arg in ("rule-based", "llm")]
if "llm" in WAYS:
    os.environ["LLM_ENABLED"] = "true"
    os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
else:
    os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.service import TopicNotFoundError  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
M2V = sys.argv[sys.argv.index("--m2v") + 1] if "--m2v" in sys.argv else "JanSchachtschabel/m2v-gte-256-edu"
TOPICS = [
    "Evolution", "Reformation", "Absolutismus", "Ozonschicht", "Nervensystem", "Vulkanismus", "Menschenrechte",
    "Kalter Krieg", "Romantik", "Satz des Thales", "Prozentrechnung", "Wahrscheinlichkeit", "Säugetiere",
    "Periodensystem", "Kernspaltung", "Globalisierung", "Dreißigjähriger Krieg", "Impressionismus", "Schall",
    "Genetik",
    "Biologie: Blatt", "Chemie: Salz", "Mathematik: Körper", "Musik: Stimme", "Physik: Feder", "Erdkunde: Becken",
    "Informatik: Speicher", "Kunst: Perspektive", "Sport: Ausdauer",
    "Kreislauf des Blutes",
]
TOPICS_M25 = [
    "Elektromagnetische Induktion", "Kernfusion", "Ottomotor", "Mitose", "Enzym", "Immunsystem", "Hormon",
    "Quadratische Funktion", "Integralrechnung", "Vektor", "Mittelalter", "Aufklärung", "Monsun", "Gletscher", "Wüste",
    "Sozialstaat", "Bundestag", "Inflation", "Marktwirtschaft", "Algorithmus", "Datenbank", "Verschlüsselung", "Lyrik",
    "Kurzgeschichte", "Expressionismus", "Oper", "Chemische Bindung", "Redoxreaktion", "Radioaktivität", "Magnetismus",
]
if "--m25" in sys.argv:
    TOPICS = TOPICS_M25

out_path = Path(sys.argv[1])
service = cli_service(ZIMS)
service.settings.model2vec_path = M2V
knows_switch = "article_choice" in GenerateRequest.model_fields


def request(topic: str, way: str) -> GenerateRequest:
    extra = {"article_choice": way} if knows_switch else {}
    return GenerateRequest(topic=topic, parts=["world"], **extra)


for topic in TOPICS:  # warm: archive pages, the model, the lexicon; the rules only, so no prompt is spent
    try:
        service.generate(request(topic, "rule-based"))
    except TopicNotFoundError:
        pass

rows: list[dict] = []
for index, topic in enumerate(TOPICS):
    order = WAYS if index % 2 == 0 else list(reversed(WAYS))
    for way in order:
        started = time.perf_counter()
        try:
            result = service.generate(request(topic, way))
        except TopicNotFoundError:
            rows.append({"thema": topic, "weg": way, "gefunden": False})
            continue
        seconds = time.perf_counter() - started
        choice = (result.audit.llm or {}).get("article_choice") or {}
        rows.append({
            "thema": topic, "weg": way, "gefunden": True, "sekunden": round(seconds, 3),
            "phasen_ms": dict(result.audit.timings_ms), "titel": result.resolution.title,
            "methode": getattr(result.resolution, "method", None),
            "sicher": getattr(result.resolution, "confident", None),
            "tokens": (result.audit.llm_tokens or {}).get("total", 0),
            "gefragt": bool(choice.get("asked")), "treffer_geprueft": choice.get("hits_checked", 0),
            "treffer_verworfen": choice.get("hits_dropped", []),
        })
        print(f"{way:10s} {seconds:6.2f} s  {topic:24s} -> {result.resolution.title}", flush=True)


def quantile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


summary: dict[str, dict] = {}
for way in WAYS:
    done = [r for r in rows if r["weg"] == way and r["gefunden"]]
    seconds = [r["sekunden"] for r in done]
    summary[way] = {
        "themen": len(done), "median_s": round(statistics.median(seconds), 2),
        "p90_s": round(quantile(seconds, 0.9), 2), "mittel_s": round(statistics.mean(seconds), 2),
        "tokens": sum(r["tokens"] for r in done), "llm_gefragt": sum(r["gefragt"] for r in done),
        "treffer_geprueft": sum(1 for r in done if r["treffer_geprueft"]),
    }
    print(way, summary[way])
if set(WAYS) == {"rule-based", "llm"}:
    by_topic = {(r["thema"], r["weg"]): r for r in rows if r["gefunden"]}
    extra = [
        by_topic[(t, "llm")]["sekunden"] - by_topic[(t, "rule-based")]["sekunden"]
        for t in TOPICS
        if (t, "llm") in by_topic and (t, "rule-based") in by_topic
    ]
    summary["llm_mehr"] = {
        "median_s": round(statistics.median(extra), 2), "p90_s": round(quantile(extra, 0.9), 2),
        "max_s": round(max(extra), 2),
    }
    print("llm mehr als rule-based je Thema:", summary["llm_mehr"])
out_path.write_text(json.dumps({"zusammenfassung": summary, "laeufe": rows}, ensure_ascii=False, indent=1), "utf-8")
