"""Messskript M56 (Audit A05, 03.10.2026): ein Prototyp ohne Hauptartikel, nicht eingebaut. Er ließ in
CompendiumService.prepare ein Thema ohne Archivartikel weiterlaufen, wenn die Anfrage eine Wissens-Sammlung
nennt (404 erst, wenn auch die Materialien nichts bringen). Lief mit dem Prototyp im Arbeitsbaum in einem
Einmal-Container mit den Archiven:

  docker compose run --rm --no-deps -T -v "$(pwd -W)/app:/src/app:ro" -e PYTHONPATH=/src api \
      python - '["<Thema>", ...]' < mc_ohne_hauptartikel.py

Ergebnis als JSON nach der Zeile JSON-START; Auswertung siehe docs/entwicklung/05-messprotokoll.md (M56).
"""
import json
import sys

from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.main import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

OPTIK = "9e7ae956-e9df-430f-bace-f3db4b910013"
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
out = []
for topic in json.loads(sys.argv[1]):
    request = GenerateRequest(topic=topic, preset="llm-free", parts=["world"], knowledge_collection_id=OPTIK, knowledge_fulltext=True)
    try:
        result = service.generate(request)
    except TopicNotFoundError as exc:
        out.append({"topic": topic, "error": "404"})
        continue
    blocks = [{"titel": s.title, "status": s.status.value, "text": s.text[:1500],
               "quellen": sorted({c.source_title for c in s.citations})} for s in result.sections if s.text and s.slot_key not in ("quellen", "glossar")]
    out.append({"topic": topic, "resolution": result.resolution.title, "parts_status": result.parts_status,
                "sources": len(result.sources), "chunks": result.audit.chunks_total, "knowledge": result.audit.knowledge,
                "lint": [f.rule for f in result.audit.lint], "blocks": blocks})
    print(f"# {topic}: sources {len(result.sources)}, blocks with text {len(blocks)}", file=sys.stderr)
print("JSON-START")
print(json.dumps(out, ensure_ascii=False))
