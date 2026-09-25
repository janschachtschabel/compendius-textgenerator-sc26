"""Time of the four profiles per compendium (M27b), each LLM profile on topics of its own.

M27 ran every profile on the same six topics; there the b-api's answer cache served the profile that came second
with the prompts of the one before it (the article choice of balanced, best-quality and best-quality-generated is
the same prompt, and so is the matching of the last two), so its time was too short while its tokens stayed right.
Here each LLM profile gets six topics of its own, 18 topics no measurement asked before, and llm-free runs on all
of them, since it sends no prompt. Otherwise as M27: part 1 and part 2, LLM_MAX_TOKENS_PER_REQUEST 100 000, a warm
pass llm-free first.

Usage (project venv, from the project root; B_API_KEY in .env, never printed):
python docs/entwicklung/messung/mc_profile_zeit.py <out.json> --m2v <model directory>
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
SETS = {
    "balanced": ["Stochastik", "Nahrungskette", "Erster Weltkrieg", "Rechtsstaat", "Barock", "Magnetfeld"],
    "best-quality": ["Hebelgesetz", "Mondphasen", "Industrialisierung", "Blutkreislauf", "Kreiszahl", "Sonett"],
    "best-quality-generated": ["Schwerkraft", "Elektromagnet", "Hanse", "Verdauung", "Primzahl", "Kubismus"],
}
TOPICS = [topic for topics in SETS.values() for topic in topics]
PARTS = ["world", "curricula"]


def run(service: Any, topic: str, profile: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = service.generate(GenerateRequest(topic=topic, preset=profile, parts=PARTS))  # type: ignore[arg-type]
    seconds = time.perf_counter() - started
    audit, llm = result.audit, result.audit.llm or {}
    tokens = audit.llm_tokens or {}
    enrichment = (result.frontmatter.get("llm") or {}).get("enrichment") or {}
    matching = llm.get("matching") or {}
    generation = llm.get("generation") or {}
    choice = llm.get("article_choice") or {}
    return {
        "profil": audit.preset,
        "hauptartikel": result.resolution.title,
        "sekunden": round(seconds, 2),
        "phasen_ms": audit.timings_ms,
        "aufrufe": tokens.get("calls", 0),
        "tokens": tokens.get("total", 0),
        "matcher": audit.matcher,
        "extraction": result.extraction,
        "generation": result.generation,
        "enrichment": result.enrichment,
        "bausteine_gefuellt": audit.sections_filled,
        "absaetze_zugeordnet": audit.chunks_assigned,
        "absaetze_gesamt": audit.chunks_total,
        "lehrplanelemente": len(result.curricula.entries) if result.curricula else 0,
        "artikelwahl": {key: choice.get(key) for key in ("used", "asked", "chosen", "hits_dropped")},
        "zuordnung": {key: matching.get(key) for key in ("used", "paragraphs", "answered", "fallback_paragraphs")},
        "generierung": {key: generation.get(key) for key in ("used", "sections", "fallbacks")},
        "modellwissen_saetze": enrichment.get("marked_sentences", 0),
        "hinweis": llm.get("note"),
        "zeichen_teil1": sum(len(section.text) for section in result.sections),
        "_text": "\n\n".join(f"## {section.title}\n\n{section.text}" for section in result.sections if section.text),
    }


out_path = Path(sys.argv[1])
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
service = cli_service(ZIMS)
service.settings.model2vec_path = sys.argv[sys.argv.index("--m2v") + 1]
if service.llm is None or service.llm_unavailable() is not None:
    raise SystemExit(f"LLM nicht verfügbar: {service.llm_unavailable()}")

free: dict[str, Any] = {}
for topic in TOPICS:  # warm pass, then the timed llm-free pass
    service.generate(GenerateRequest(topic=topic, preset="llm-free", parts=PARTS))
for topic in TOPICS:
    row = run(service, topic, "llm-free")
    row.pop("_text")
    free[topic] = row
print("llm-free fertig", flush=True)

runs: dict[str, dict[str, Any]] = {"llm-free": free}
for index in range(6):  # the profiles take turns, topic by topic
    for profile, topics in SETS.items():
        topic = topics[index]
        row = run(service, topic, profile)
        row.pop("_text")
        runs.setdefault(profile, {})[topic] = row
        print(
            f"{topic:24} {profile:23} {row['sekunden']:6.1f} s {row['tokens']:6} Tok {row['aufrufe']:3} Aufr "
            f"{row['hauptartikel'][:24]:24} Absaetze {row['absaetze_gesamt']:4} {row['hinweis'] or ''}",
            flush=True,
        )

summary: dict[str, Any] = {}
for profile, rows_by_topic in runs.items():
    rows = list(rows_by_topic.values())
    summary[profile] = {
        "themen": len(rows),
        "sekunden_median": round(statistics.median(r["sekunden"] for r in rows), 2),
        "sekunden_min_max": [min(r["sekunden"] for r in rows), max(r["sekunden"] for r in rows)],
        "tokens_median": statistics.median(r["tokens"] for r in rows),
        "tokens_min_max": [min(r["tokens"] for r in rows), max(r["tokens"] for r in rows)],
        "absaetze_median": statistics.median(r["absaetze_gesamt"] for r in rows),
        "hinweise": [r["hinweis"] for r in rows if r["hinweis"]],
    }
    print(profile, json.dumps(summary[profile], ensure_ascii=False), flush=True)
free_by_set = {
    profile: round(statistics.median(free[topic]["sekunden"] for topic in topics), 2) for profile, topics in SETS.items()
}
out_path.write_text(
    json.dumps({"saetze": SETS, "llm_free_median_je_satz": free_by_set, "zusammenfassung": summary, "laeufe": runs},
               ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(f"llm-free je Satz: {free_by_set}")
