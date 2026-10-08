"""Messskript M71, Teil 3 (08.10.2026): der eingebaute Sammlungskontext an der Stichprobe, und das Thema der
schreibenden Profile mit dem Baum.

Je Sammlung der Stichprobe (mc_sammlungskontext.py) läuft im Einmal-Container mit dem eingehängten Arbeitsstand:

- BR: ``llm-free`` mit der Sammlung als node_id - die Regeln lösen bei neutralem Titel die nächste sprechende
  Sammlung darüber auf (zu vergleichen mit R1 aus Teil 2);
- BN: ``balanced`` mit der Sammlung als node_id - die Frage N hört den Ort im Baum (zu vergleichen mit N3);
- W0: die Themenformulierung der schreibenden Profile (D72) aus den Angaben der Sammlung, wie heute;
- W1: dieselbe mit dem Ort im Baum als weiterer Zeile („Lage im Themenbaum: …“, wie N3 ihn hört).

LLM über OpenAI direkt (mc_openai_direkt.py), Arbeitsstand eingehängt (``-v <app>:/src/app:ro -e PYTHONPATH=/src``):

  cat mc_openai_direkt.py mc_sammlungskontext_bau.py | docker compose run --rm --no-deps -T -v <ordner>:/x:ro \
      -v <app>:/src/app:ro -e PYTHONPATH=/src -e LLM_ENABLED=true -e B_API_KEY=direct \
      -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY api python - /x/stichprobe.json

Ergebnis als JSON nach der Zeile JSON-START.
"""

# --- M71, part 3: the built collection context, and the wording of a collection's topic with its tree ---
import json
import sys

install()
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import ArticleChoiceJob
from app.knowledge.collection_context import describe
from app.knowledge.topic_wording import TopicWordingReport, metadata_input, word_topic
from app.llm.deadline import Deadline
from app.wiring import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

sample = json.loads(open(sys.argv[1], encoding="utf-8").read())
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())


def prepared_for(preset, node_id):
    deadline = Deadline(settings.request_time_limit_s)
    request, profile = service._admit(GenerateRequest(node_id=node_id, parts=["world"], preset=preset), deadline)
    budget = service.open_budget(profile)
    _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
    budget = choice.budget if choice is not None else budget
    wording = service.wording_job(request.generation, choice, deadline, budget)
    return service.prepare(request, deadline, choice, wording=wording)


def run(preset, node_id):
    try:
        prepared = prepared_for(preset, node_id)
    except TopicNotFoundError:
        return {"main": None, "named": [], "error": "404"}
    articles = prepared.articles
    return {
        "main": prepared.resolution.title or None,
        "method": prepared.resolution.method,
        "rules_topic": prepared.resolution.normalized,
        "named": list(articles.found) if articles is not None else [],
        "asked": prepared.asked_topic,
    }


def worded(text):
    job = ArticleChoiceJob(service.llm.client, service.llm.open_budget(), Deadline(settings.request_time_limit_s))
    report = TopicWordingReport()
    return {"topic": word_topic(job, text, report), "fallback": report.fallback}


rows = []
for entry in sample:
    info, _ = service.read_node(entry["id"])
    tree = service.collection_tree(info, None, None)
    labels = service.subjects.labels_of(list(info.subject_uris))
    base = metadata_input(info)
    place = describe(tree, labels)
    result = {
        "BR": run("llm-free", entry["id"]),
        "BN": run("balanced", entry["id"]),
        "W0": worded(base),
        "W1": worded(f"{base}\nLage im Themenbaum: {place}"),
    }
    rows.append({**entry, "baum": {"path": list(tree.path), "place": place}, "bau": result})
    print(
        f"# {entry['title']} ({' > '.join(tree.path)}): BR {result['BR']['main']} | BN {result['BN']['main']} | "
        f"W0 {result['W0']['topic']} | W1 {result['W1']['topic']} | shown {result['BR'].get('asked')}",
        file=sys.stderr,
        flush=True,
    )

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
