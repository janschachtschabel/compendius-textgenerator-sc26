"""The four profiles per compendium (M27): time, tokens and what each did, on six topics no measurement asked before.

Topics no earlier measurement asked, so no prompt comes out of the b-api's cache: six school topics of six subjects.
Each runs through CompendiumService.generate with part 1 and part 2 (parts world and curricula), once per profile,
the profiles taking turns per topic so the b-api's speed of the moment spreads over all of them. Before the timed
pass every topic runs once llm-free, so the archive files and Model2Vec are warm. LLM_MAX_TOKENS_PER_REQUEST is
100 000, the budget the decision paper recommends for best-quality.

Per run: wall time, the phases of the service, calls and tokens of the LLM, the main article, filled blocks,
assigned paragraphs, curriculum entries, what the LLM steps did (article choice, matching, generation) and the
sentences marked as model knowledge. The part-1 texts of best-quality and best-quality-generated go to <texts_dir>
for the judges of the readable version (M28); they hold Wikipedia text and stay outside the repository.

Usage (project venv, from the project root; B_API_KEY in .env, never printed):
python docs/entwicklung/messung/mc_profile.py <out.json> <texts_dir> --m2v <model directory>
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
TOPICS = ["Zellatmung", "Elektrischer Widerstand", "Kolonialismus", "Lineare Gleichung", "Renaissance", "Klimazonen"]
PROFILES = ["llm-free", "balanced", "best-quality", "best-quality-generated"]
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


out_path, texts_dir = Path(sys.argv[1]), Path(sys.argv[2])
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
texts_dir.mkdir(parents=True, exist_ok=True)
service = cli_service(ZIMS)
service.settings.model2vec_path = sys.argv[sys.argv.index("--m2v") + 1]
if service.llm is None or service.llm_unavailable() is not None:
    raise SystemExit(f"LLM nicht verfügbar: {service.llm_unavailable()}")

for topic in TOPICS:  # warm: archive files, Model2Vec, no LLM
    service.generate(GenerateRequest(topic=topic, preset="llm-free", parts=PARTS))
print("warm", flush=True)

runs: dict[str, dict[str, Any]] = {}
for index, topic in enumerate(TOPICS):
    runs[topic] = {}
    for profile in PROFILES[index % 4 :] + PROFILES[: index % 4]:
        row = run(service, topic, profile)
        text = row.pop("_text")
        if profile in ("best-quality", "best-quality-generated"):
            (texts_dir / f"{topic}__{profile}.md").write_text(text, encoding="utf-8")
        runs[topic][profile] = row
        print(
            f"{topic:24} {profile:23} {row['sekunden']:6.1f} s {row['tokens']:6} Tok {row['aufrufe']:3} Aufr "
            f"{row['hauptartikel'][:24]:24} Bausteine {row['bausteine_gefuellt']:2} "
            f"Modellwissen {row['modellwissen_saetze']:2} {row['hinweis'] or ''}",
            flush=True,
        )

summary: dict[str, Any] = {}
for profile in PROFILES:
    rows = [runs[topic][profile] for topic in TOPICS]
    summary[profile] = {
        "sekunden_median": round(statistics.median(r["sekunden"] for r in rows), 2),
        "sekunden_min_max": [min(r["sekunden"] for r in rows), max(r["sekunden"] for r in rows)],
        "tokens_median": statistics.median(r["tokens"] for r in rows),
        "tokens_min_max": [min(r["tokens"] for r in rows), max(r["tokens"] for r in rows)],
        "aufrufe_median": statistics.median(r["aufrufe"] for r in rows),
        "bausteine_median": statistics.median(r["bausteine_gefuellt"] for r in rows),
        "modellwissen_saetze_summe": sum(r["modellwissen_saetze"] for r in rows),
        "hinweise": [r["hinweis"] for r in rows if r["hinweis"]],
    }
    print(profile, json.dumps(summary[profile], ensure_ascii=False), flush=True)

out_path.write_text(
    json.dumps({"themen": TOPICS, "zusammenfassung": summary, "laeufe": runs}, ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(f"\n{len(TOPICS)} Themen nach {out_path}")
