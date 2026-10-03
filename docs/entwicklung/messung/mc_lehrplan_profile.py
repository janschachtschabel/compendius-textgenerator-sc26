"""Messskript M57 (03.10.2026): Teil 2 in llm-free, balanced und best-quality. Läuft in einem Einmal-Container mit
den Archiven und dem Lehrplan-Cache, das LLM über OpenAI direkt:

  cat mc_openai_direkt.py mc_lehrplan_profile.py | docker compose run --rm --no-deps -T -e LLM_ENABLED=true \
      -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY api python - '<themen.json>'

Ergebnis als JSON nach der Zeile JSON-START; Auswertung und Noten siehe docs/entwicklung/05-messprotokoll.md (M57).
"""

# --- M57: part 2 in every profile (llm-free, balanced, best-quality; the generating profiles share best-quality's part 2) ---
import json
import sys
import time

install()
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.main import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

topics = json.loads(sys.argv[1])
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
assert service.llm is not None and service.curricula is not None
keep = ("iri", "label", "bereich", "lehrplan", "bundesland", "schulfaecher", "schulstufe", "keyword", "matched_in", "note", "score")
out = []
for kind, names in topics.items():
    for topic in names:
        for preset in ("llm-free", "balanced", "best-quality"):
            started = time.perf_counter()
            try:
                result = service.generate(GenerateRequest(topic=topic, preset=preset, parts=["curricula"]))
            except TopicNotFoundError:
                out.append({"kind": kind, "topic": topic, "preset": preset, "error": "404"})
                continue
            part = result.curricula
            llm = result.audit.llm or {}
            out.append({
                "kind": kind, "topic": topic, "preset": preset,
                "article": result.resolution.title, "method": result.resolution.method,
                "keywords": part.keywords if part else [], "summary": {k: (part.summary or {}).get(k) for k in ("matches", "bundled", "total_hits", "cut_hits", "excluded_noise", "lehrplaene", "laender")} if part else {},
                "entries": [{k: e.get(k) for k in keep} for e in (part.entries if part else [])],
                "check": llm.get("curriculum_check"), "tokens": result.audit.llm_tokens,
                "seconds": round(time.perf_counter() - started, 1),
            })
            print(f"# {kind} {topic} {preset}: {out[-1]['summary'].get('matches')} matches, {out[-1]['seconds']} s", file=sys.stderr, flush=True)
print("JSON-START")
print(json.dumps(out, ensure_ascii=False))
