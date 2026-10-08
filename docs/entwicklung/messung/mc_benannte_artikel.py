"""Messskript M72 (08.10.2026): ob die Artikel passen, die die KI zu einem Thema benennt (Frage N, D63).

Audit 2026-10-03, F04: Die Artikel, die N zu den Teilen eines Themas nennt, prüft der Dienst nur darauf, ob es sie gibt
und ob sie keine Begriffsklärung sind; ihre Absätze brauchen das Thema nicht zu nennen. Wie viele davon nicht zum
Thema passen, zeigt nur ein Lauf im Ablauf des Dienstes: ``balanced`` bis zum Korpus, je Thema die benannten Artikel,
die der Korpus nahm, mit dem Anfang ihrer Einleitung für eine blinde Bewertung. Die Themen: gewöhnliche, Sammelthemen
(M37) und Aspektthemen (M47), damit dieselbe Messung zeigt, was N bei einem Aspekt nennt.

Einmal-Container mit den Archiven, LLM über OpenAI direkt (mc_openai_direkt.py):

  cat mc_openai_direkt.py mc_benannte_artikel.py | docker compose run --rm --no-deps -T \
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY \
      api python - [<profil>]

Ergebnis als JSON nach der Zeile JSON-START.
"""

# --- M72: the articles question N names, with the start of their lead, for a blind check ---
import json
import sys

install()
from app.domain.requests import GenerateRequest
from app.knowledge.corpus_sources import NAMED_ORIGIN
from app.llm.deadline import Deadline
from app.wiring import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

GEWOEHNLICH = [
    "Optik", "Photosynthese", "Französische Revolution", "Klimawandel", "Bruchrechnung", "Ohmsches Gesetz",
    "Demokratie", "Zellteilung", "Vulkan", "Industrialisierung", "Grundgesetz", "Magnetismus", "Wasserkreislauf",
    "Römisches Reich", "Kalter Krieg", "Evolution", "Reformation", "Sonnensystem", "Lyrik", "Plattentektonik",
]
SAMMEL = [
    "deutsche Dichter", "Dichter der Romantik", "Komponisten der Klassik", "Philosophen der Aufklärung",
    "Maler des Impressionismus", "römische Kaiser", "deutsche Bundeskanzler", "griechische Götter",
    "Planeten des Sonnensystems", "Edelgase", "Weltreligionen", "erneuerbare Energien", "Entdecker der Neuzeit",
    "Frauen in der Wissenschaft", "Märchen der Brüder Grimm",
]
ASPEKT = [
    "OER-Förderungen", "Projektmanagement von agilen Projekten", "Künstliche Intelligenz im Unterricht",
    "Digitale Bildung in der Grundschule", "Klimawandel in der Landwirtschaft", "Inklusion im Sportunterricht",
    "Datenschutz an Schulen", "Nachhaltigkeit im Schulalltag",
]
LEAD_CHARS = 600

preset = sys.argv[1] if len(sys.argv) > 1 else "balanced"
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())


def prepared_for(topic):
    """The start of generate with its LLM jobs: admission, budget, the article choice (question N with it), the
    wording; prepare alone runs the rules only."""
    deadline = Deadline(settings.request_time_limit_s)
    request, profile = service._admit(GenerateRequest(topic=topic, parts=["world"], preset=preset), deadline)
    budget = service.open_budget(profile)
    _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
    budget = choice.budget if choice is not None else budget
    wording = service.wording_job(request.generation, choice, deadline, budget)
    return service.prepare(request, deadline, choice, wording=wording)


def lead(source):
    for section in source.sections:
        for paragraph in section.paragraphs:
            if paragraph.text.strip():
                return paragraph.text.strip()[:LEAD_CHARS]
    return ""


rows = []
for kind, topics in (("gewoehnlich", GEWOEHNLICH), ("sammel", SAMMEL), ("aspekt", ASPEKT)):
    for topic in topics:
        try:
            prepared = prepared_for(topic)
        except Exception as exc:  # a measurement records the failure and goes on
            rows.append({"topic": topic, "kind": kind, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        articles = prepared.articles
        named = [s for s in prepared.sources if s.origin == NAMED_ORIGIN]
        rows.append(
            {
                "topic": topic,
                "kind": kind,
                "main": prepared.resolution.title,
                "method": prepared.resolution.method,
                "overview": articles.overview if articles else None,
                "named": list(articles.named) if articles else [],
                "found": list(articles.found) if articles else [],
                "covers": articles.covers if articles else None,
                "corpus": [{"title": s.title, "lead": lead(s)} for s in named],
            }
        )
        print(f"# {topic}: {prepared.resolution.title}, {len(named)} benannte im Korpus", file=sys.stderr, flush=True)

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
