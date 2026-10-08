"""Messskript M70 (04.10.2026): welchen Artikel eine lange Eingabe findet, mit und ohne das formulierte Thema.

Audit 2026-10-03, F05: Die Artikelwahl (``choose_main_article``) läuft vor der Themenformulierung (D72); eine lange
Eingabe oder eine Frage geht also als Text in die Auflösung, und erst danach formuliert die KI in den schreibenden
Profilen ein Thema für die Prompts. Findet die Auflösung nichts, endet die Anfrage mit 404, bevor das formulierte
Thema helfen könnte. Dieses Skript läuft den Anfang einer Anfrage wie ``CompendiumService.generate`` bis zum Korpus,
ohne zu schreiben, je Eingabe

- ``wie_heute``: im Profil (Vorgabe best-quality-generated) mit der Eingabe als Thema, wie der Dienst es tut;
- ``formuliert``: dasselbe Profil mit dem Thema, das die KI in ``wie_heute`` formulierte, als Thema - so, als käme die
  Formulierung vor der Artikelwahl.

Einmal-Container mit den Archiven, LLM über OpenAI direkt (mc_openai_direkt.py):

  cat mc_openai_direkt.py mc_lange_eingaben.py | docker compose run --rm --no-deps -T -v <ordner>:/x:ro \
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY \
      api python - /x/eingaben.json [<profil>]

Ergebnis als JSON nach der Zeile JSON-START: je Eingabe und Variante Hauptartikel, Verfahren, die von der KI
genannten Artikel, das formulierte Thema oder der Fehler (404).
"""

# --- M70: the article a long input finds, as asked and as worded ---
import json
import sys

install()
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.llm.deadline import Deadline
from app.wiring import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

inputs = json.loads(open(sys.argv[1], encoding="utf-8").read())
preset = sys.argv[2] if len(sys.argv) > 2 else "best-quality-generated"
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())


def prepared_for(topic):
    """The start of generate: admission, budget, the article choice and the wording, then prepare."""
    deadline = Deadline(settings.request_time_limit_s)
    request, profile = service._admit(GenerateRequest(topic=topic, parts=["world"], preset=preset), deadline)
    budget = service.open_budget(profile)
    _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
    budget = choice.budget if choice is not None else budget
    wording = service.wording_job(request.generation, choice, deadline, budget)
    try:
        prepared = service.prepare(request, deadline, choice, wording=wording)
    except TopicNotFoundError as exc:
        return {"topic": topic, "error": "404", "alternatives": list(exc.resolution.alternatives)[:5]}
    articles = prepared.articles
    return {
        "topic": topic,
        "main": prepared.resolution.title,
        "method": prepared.resolution.method,
        "asked_topic": prepared.asked_topic,
        "worded": prepared.wording.topic if prepared.wording is not None else None,
        "named": list(articles.found) if articles is not None else [],
        "sources": [source.title for source in prepared.sources][:12],
    }


rows = []
for text in inputs:
    today = prepared_for(text)
    worded = today.get("worded")
    rows.append({"input": text, "wie_heute": today, "formuliert": prepared_for(worded) if worded else None})
    print(f"# {text[:50]}: {today.get('main') or today.get('error')} / {worded}", file=sys.stderr, flush=True)

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
