"""Messskript (Audit-Nachgang 03.10.2026), läuft im Entwicklungscontainer mit den Archiven:

  cat mc_openai_direkt.py mc_lehrplan_teile.py | docker exec -i -w /app -e PYTHONPATH=/app -e LLM_ENABLED=true \
      -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY <container> python - <argumente>

Ergebnis als JSON nach der Zeile JSON-START; Auswertung und Noten siehe docs/entwicklung/05-messprotokoll.md (M54-M56).
"""

# --- A06: part 2 with the sub-topics of today and with the parts question N names (service flow) ---
import json
import sys

install()
from app.domain.requests import GenerateRequest
from app.llm.deadline import Deadline
from app.wiring import build_registry, build_service
from app.settings import get_settings
from app.sources.zim.registry import NAMED_ORIGIN
from app.templates.manager import TemplateManager

topics = json.loads(sys.argv[1])
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
assert service.llm is not None and service.curricula is not None
print("curricula state:", service.curricula.store.state, file=sys.stderr)
keep = ("iri", "label", "keyword", "fach", "bundesland", "matched_in", "score", "parent_label")
out = []
for kind, names in topics.items():
    for topic in names:
        request = GenerateRequest(topic=topic, preset="balanced", parts=["world", "curricula"])
        deadline = Deadline(settings.request_time_limit_s)
        request, profile = service._admit(request, deadline)
        budget = service.open_budget(profile)
        _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
        prepared = service.prepare(request, deadline, choice)
        named = [s.title for s in prepared.sources if s.origin == NAMED_ORIGIN]
        widened = [*prepared.subtopics, *(t for t in named if t not in prepared.subtopics)]
        runs = {}
        for name, subtopics in (("heute", prepared.subtopics), ("mit_teilen", widened)):
            part = service.curricula.build(
                title=prepared.title, aliases=prepared.aliases, subtopics=subtopics,
                subjects=prepared.subjects, facets_visible=False,
            )
            runs[name] = {"keywords": part.keywords, "entries": [{k: e.get(k) for k in keep} for e in part.entries]}
        out.append({"kind": kind, "topic": topic, "title": prepared.title, "named": named, "subtopics": prepared.subtopics, **runs})
        print(f"# {kind} {topic}: {len(runs['heute']['entries'])} -> {len(runs['mit_teilen']['entries'])} entries", file=sys.stderr)
print("JSON-START")
print(json.dumps(out, ensure_ascii=False))
