"""Messskript (Audit-Nachgang 03.10.2026), läuft im Entwicklungscontainer mit den Archiven:

  cat mc_openai_direkt.py mc_genannte_teile.py | docker exec -i -w /app -e PYTHONPATH=/app -e LLM_ENABLED=true \
      -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY <container> python - <argumente>

Ergebnis als JSON nach der Zeile JSON-START; Auswertung und Noten siehe docs/entwicklung/05-messprotokoll.md (M54-M56).
"""

# --- A02: the parts question N names, linked with the main article or not (service flow up to the corpus) ---
import json
import sys

install()
from app.domain.requests import GenerateRequest
from app.llm.deadline import Deadline
from app.wiring import build_registry, build_service
from app.settings import get_settings
from app.sources.zim.registry import NAMED_ORIGIN, LinkedTo
from app.templates.manager import TemplateManager

topics = json.loads(sys.argv[1])
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
assert service.llm is not None
out = []
for kind, names in topics.items():
    for topic in names:
        request = GenerateRequest(topic=topic, preset="balanced", parts=["world"])
        deadline = Deadline(settings.request_time_limit_s)
        request, profile = service._admit(request, deadline)
        budget = service.open_budget(profile)
        _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
        prepared = service.prepare(request, deadline, choice)
        primary = next(s for s in prepared.sources if s.is_primary)
        archive = next(a for a in prepared.registry.archives if a.project == primary.project)
        linked_to = LinkedTo(archive, primary)
        report = prepared.articles
        out.append({
            "kind": kind, "topic": topic, "main": primary.title, "method": prepared.resolution.method,
            "overview": report.overview if report else None, "found": report.found if report else [],
            "covers": report.covers if report else None, "fallback": report.fallback if report else None,
            "named": [{"title": s.title, "linked": linked_to(s)} for s in prepared.sources if s.origin == NAMED_ORIGIN],
            "tokens": budget.spent if hasattr(budget, "spent") else None,
        })
        print(f"# {kind} {topic}: main {primary.title}, named {len(out[-1]['named'])}, unlinked {sum(not n['linked'] for n in out[-1]['named'])}", file=sys.stderr)
print("JSON-START")
print(json.dumps(out, ensure_ascii=False))
