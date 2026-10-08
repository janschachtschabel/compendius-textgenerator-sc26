"""Messskript M71, Teil 2 (08.10.2026): welcher Kontext einer Sammlung zu ihrem Artikel führt - trennscharf.

Je Sammlung der Stichprobe (mc_sammlungskontext.py; inhaltsneutrale Titel wie „Grundlagen“ und Kontrollen mit
sprechendem Titel) läuft im Einmal-Container:

- R0: ``llm-free`` mit der Sammlung als node_id, wie heute (der Titel ist das Thema);
- R1: ``llm-free`` mit dem Titel der nächsten übergeordneten Sammlung als Thema (ohne Pfad das Fach) und der Sammlung
  als node_id - was die Regeln mit dem Pfad tun könnten;
- N0: ``balanced`` mit der Sammlung als node_id, wie heute: die Frage N hört Titel und Fach;
- N1: die Frage N hört dazu den Pfad im Themenbaum;
- N2: dazu die eigenen Untersammlungen und die Titel der ersten Materialien - was in dieser Sammlung liegt;
- N3: dazu die Nachbarsammlungen, ausdrücklich als nicht gemeint - nur zum Abgrenzen, nicht als Inhalt.

N1 bis N3 stellen die Frage N wie der Dienst (``ask_topic_articles``); ihr Hauptartikel ist die genannte Übersicht.
Pfad, Untersammlungen, Materialien und Nachbarn liest das Skript ohne Anmeldung aus dem konfigurierten Repository.
LLM über OpenAI direkt (mc_openai_direkt.py):

  cat mc_openai_direkt.py mc_sammlungskontext_messung.py | docker compose run --rm --no-deps -T -v <ordner>:/x:ro \
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY \
      api python - /x/stichprobe.json

``stichprobe.json``: Liste von Objekten mit id, title, subjects, path, children, materials, art (neutral|kontrolle).
Ergebnis als JSON nach der Zeile JSON-START.
"""

# --- M71: the context of a collection as the article choice could hear it ---
import json
import sys

import httpx

install()
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import ArticleChoiceJob
from app.knowledge.topic_articles import ask_topic_articles
from app.llm.deadline import Deadline
from app.wiring import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

MAX_CHILDREN, MAX_MATERIALS, MAX_SIBLINGS = 10, 8, 10

sample = json.loads(open(sys.argv[1], encoding="utf-8").read())
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
archive = service.registry.primary_archive
rest = settings.edu_sharing_base_url.rstrip("/")


def siblings(entry):
    """The other sub-collections of the collection's parent: for telling apart, never as content."""
    with httpx.Client(timeout=30.0, headers={"Accept": "application/json"}) as http:
        own = http.get(f"{rest}/collection/v1/collections/-home-/{entry['id']}").json()["collection"]
        parent = ((own.get("properties") or {}).get("virtual:primaryparent_nodeid") or [""])[0]
        if not parent:
            return []
        subs = http.get(f"{rest}/collection/v1/collections/-home-/{parent}/children/collections",
                        params={"maxItems": 60}).json().get("collections") or []
    return [s.get("title") or "" for s in subs if s["ref"]["id"] != entry["id"]]


def prepared_for(preset, *, topic=None, node_id=None):
    deadline = Deadline(settings.request_time_limit_s)
    request, profile = service._admit(
        GenerateRequest(topic=topic, node_id=node_id, parts=["world"], preset=preset), deadline
    )
    budget = service.open_budget(profile)
    _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
    budget = choice.budget if choice is not None else budget
    wording = service.wording_job(request.generation, choice, deadline, budget)
    return service.prepare(request, deadline, choice, wording=wording)


def run(preset, **kwargs):
    try:
        prepared = prepared_for(preset, **kwargs)
    except TopicNotFoundError:
        return {"main": None, "named": [], "error": "404"}
    articles = prepared.articles
    return {
        "main": prepared.resolution.title or None,
        "method": prepared.resolution.method,
        "named": list(articles.found) if articles is not None else [],
        "asked": prepared.asked_topic,
    }


def ask(heard, subjects):
    job = ArticleChoiceJob(service.llm.client, service.llm.open_budget(), Deadline(settings.request_time_limit_s))
    report = ask_topic_articles(job, archive, heard, subjects)
    return {"main": report.found[0] if report.found else None, "named": list(report.found), "heard": heard,
            "fallback": report.fallback}


rows = []
for entry in sample:
    title, path = entry["title"].strip(), entry["path"]
    subjects = entry["subjects"]
    try:
        near = siblings(entry)
    except httpx.HTTPError:
        near = []
    entry["siblings"] = near
    place = f"Sammlung im Themenbaum unter: {' › '.join(path)}" if path else (
        f"Sammlung im Fachportal {subjects[0]}" if subjects else "Sammlung")
    inside = []
    if entry["children"]:
        inside.append("ihre Untersammlungen: " + ", ".join(entry["children"][:MAX_CHILDREN]))
    if entry["materials"]:
        inside.append("Materialien darin: " + ", ".join(entry["materials"][:MAX_MATERIALS]))
    n1 = f"{title} – {place}"
    n2 = "; ".join([n1, *inside])
    n3 = n2 + (f"; nicht gemeint sind die Nachbarsammlungen: {', '.join(near[:MAX_SIBLINGS])}" if near else "")
    above = path[-1] if path else (subjects[0] if subjects else title)
    result = {
        "R0": run("llm-free", node_id=entry["id"]),
        "R1": run("llm-free", topic=above, node_id=entry["id"]),
        "N0": run("balanced", node_id=entry["id"]),
        "N1": ask(n1, subjects),
        "N2": ask(n2, subjects),
        "N3": ask(n3, subjects),
    }
    rows.append({**entry, "varianten": result})
    print(f"# {title} ({' > '.join(path)}): R0 {result['R0']['main']} | R1 {result['R1']['main']} | "
          f"N0 {result['N0']['main']} | N1 {result['N1']['main']} | N2 {result['N2']['main']} | N3 {result['N3']['main']}",
          file=sys.stderr, flush=True)

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
