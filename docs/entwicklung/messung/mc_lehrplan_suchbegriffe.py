"""Messskript M58 (03.10.2026), ein Prototyp, nicht Teil des Dienstes: A die Frage N mit reasoning_effort none, B die
Frage N mit Lehrplan-Suchbegriffen und Schulfächern. Läuft in einem Einmal-Container, LLM über OpenAI direkt:

  cat mc_openai_direkt.py mc_lehrplan_suchbegriffe.py | docker compose run --rm --no-deps -T -e LLM_ENABLED=true \
      -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY api python - '<themen_a>' '<themen_b>'

Ergebnis als JSON nach der Zeile JSON-START; Auswertung siehe docs/entwicklung/05-messprotokoll.md (M58).
"""

# --- M58 prototype (not part of the service): question N with reasoning effort none, and with curriculum terms ---
import dataclasses
import json
import sys
import time

install()
import app.knowledge.topic_articles as topic_articles_module
import app.llm.prompts as prompts_module
from app.compendium.errors import TopicNotFoundError
from app.compendium.prepared import PreparedTopic
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import ArticleChoiceJob
from app.knowledge.topic_articles import ask_topic_articles
from app.llm.deadline import Deadline
from app.main import build_registry, build_service
from app.settings import get_settings
from app.sources.lehrplan.matcher import build_keywords
from app.templates.manager import TemplateManager

part_a_topics = json.loads(sys.argv[1])  # the 45 topics of M54
part_b_topics = json.loads(sys.argv[2])  # the 57 topics of M57
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
gateway = service.llm
archive = service.registry.primary_archive
out = {"a": [], "b": []}

# --- A: question N as shipped (v2), reasoning effort none ---
gateway.client.reasoning_effort = "none"
for kind, names in part_a_topics.items():
    for topic in names:
        job = ArticleChoiceJob(client=gateway.client, budget=gateway.open_budget(), deadline=None)
        started = time.perf_counter()
        report = ask_topic_articles(job, archive, topic)
        out["a"].append({"kind": kind, "topic": topic, "seconds": round(time.perf_counter() - started, 2),
                         "overview": report.overview, "found": report.found, "covers": report.covers,
                         "fallback": report.fallback, "tokens": report.total_tokens})
        print(f"# A {topic}: {out['a'][-1]['seconds']} s, {len(report.found)} found", file=sys.stderr, flush=True)
gateway.client.reasoning_effort = settings.llm_reasoning_effort

# --- B: question N v3 names curriculum terms; part 2 searches with them ---
V3_USER = prompts_module.TOPIC_ARTICLES.user.replace(
    "Antworte so: {{",
    "Nenne außerdem bis zu sechs kurze Suchbegriffe (lehrplan) mit ein bis drei Wörtern, unter denen das Thema, wie es "
    "gefragt ist, in deutschen Lehrplänen steht: Fachbegriffe in der Schreibweise der Schule (etwa „Fotosynthese“), "
    "Personen nur mit dem Nachnamen (etwa „Mozart“), keine Titel mit Klammerzusatz. Bei einer Gruppe nenne ihre "
    "wichtigsten Vertreter, bei einem Aspekt Begriffe, die den Aspekt selbst treffen. Keine allgemeinen Wörter wie "
    "„Musik“, „Gruppe“, „Lernen“ oder „Differenzierung“. Nenne auch die Schulfächer, in denen das Thema unterrichtet "
    "wird (faecher), mit ihrem üblichen Namen (etwa „Biologie“, „Sport“).\n"
    "Antworte so: {{",
).replace('"deckt_ab": true}}', '"deckt_ab": true, "lehrplan": ["<Begriff>", ...], "faecher": ["<Fach>", ...]}}')
assert "lehrplan" in V3_USER
prompts_module.PROMPTS["topic_articles"] = dataclasses.replace(prompts_module.TOPIC_ARTICLES, version=3, user=V3_USER)
captured = {}
original_read = topic_articles_module.read_object


def reading(text):
    data = original_read(text)
    if isinstance(data, dict) and isinstance(data.get("lehrplan"), list):
        captured["terms"] = [str(t).strip() for t in data["lehrplan"] if str(t).strip()][:6]
    if isinstance(data, dict) and isinstance(data.get("faecher"), list):
        captured["subjects"] = [str(s).strip() for s in data["faecher"] if str(s).strip()][:4]
    return data


topic_articles_module.read_object = reading
PreparedTopic.aliases = property(lambda self: [])  # the variants search with the title and the terms only
keep = ("iri", "label", "bereich", "lehrplan", "bundesland", "schulfaecher", "keyword", "matched_in", "note")


def entries(part):
    return [{k: e.get(k) for k in keep} for e in part.entries] if part else []


for kind, names in part_b_topics.items():
    for topic in names:
        for preset in ("balanced", "best-quality"):
            captured.clear()
            request = GenerateRequest(topic=topic, preset=preset, parts=["curricula"])
            deadline = Deadline(settings.request_time_limit_s)
            started = time.perf_counter()
            try:
                request, profile = service._admit(request, deadline)
                budget = service.open_budget(profile)
                _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
                prepared = service.prepare(request, deadline, choice)
            except TopicNotFoundError:
                out["b"].append({"kind": kind, "topic": topic, "preset": preset, "error": "404"})
                continue
            terms = captured.get("terms", [])
            named_subjects = captured.get("subjects", [])
            subjects = [s for s in named_subjects if service.subjects.knows(s)]
            row = {"kind": kind, "topic": topic, "preset": preset, "title": prepared.title, "terms": terms,
                   "subjects_named": named_subjects, "subjects": subjects}
            if preset == "balanced":
                for name, narrow in (("titel_und_begriffe", []), ("mit_fach", subjects)):
                    part = service.curricula.build(title=prepared.title, aliases=[], subtopics=terms,
                                                   subjects=narrow, facets_visible=False)
                    row[name] = {"keywords": part.keywords, "subject_terms": part.subject_terms,
                                 "summary": {k: part.summary.get(k) for k in ("matches", "bundled")}, "entries": entries(part)}
            else:
                prepared.subtopics = terms
                prepared.subjects = subjects
                result = service._curricula_part(prepared, request, budget, deadline)
                part = result.part
                row["mit_fach"] = {"keywords": part.keywords if part else [], "subject_terms": part.subject_terms if part else [],
                                   "summary": {k: (part.summary or {}).get(k) for k in ("matches", "bundled")} if part else {},
                                   "entries": entries(part)}
            row["seconds"] = round(time.perf_counter() - started, 1)
            row["tokens"] = getattr(budget, "spent", None)
            out["b"].append(row)
            print(f"# B {topic} {preset}: terms {terms} subjects {subjects}", file=sys.stderr, flush=True)
print("JSON-START")
print(json.dumps(out, ensure_ascii=False))
