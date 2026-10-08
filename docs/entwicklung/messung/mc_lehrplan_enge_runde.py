"""Messskript M64 (03.10.2026), ein Prototyp, nicht Teil des Dienstes: Teil 2 mit weiteren Suchwörtern, enge Runde.

Jan: „suchbegriffe und themen für teil 2 testen“. M58 zeigte: Bis zu sechs Lehrplan-Suchbegriffe der Frage N senken die
Präzision (Wortteile wie „Widerstand“ in Widerstandskämpferin, Fachbegriffe anderer Fächer), nur Aspekt-Themen mit
LLM-Prüfung gewinnen. Die enge Runde prüft, was davon trägt, je Thema mit derselben Antwort von N für alle Varianten:

- heute: Titel, Aliasse und Untertitel des Hauptartikels, wie ausgeliefert (D80: nur Note 2 einzeln, Häufigkeitsfilter);
- schulform: dazu die Schreibweise, unter der Schule und Lehrplan das Thema führen, wenn sie vom Titel abweicht
  („Brüche“ für Bruchrechnung, „Fotosynthese“ für Photosynthese);
- begriffe: dazu die Suchbegriffe von N, auf die Fächer von N begrenzt;
- thema: dazu das angefragte Thema, wenn es nicht der Titel ist.

Ein zusätzliches Suchwort zählt nur als ganzes Wort (höchstens zwei Buchstaben Endung: „Brüchen“, nicht
„Widerstandskämpferin“); Titel, Aliasse und Untertitel suchen wie heute. Die Zusätze stehen vor den Aliassen, damit die
Grenze von zwölf Suchwörtern sie nicht abschneidet. Einmal-Container mit den Archiven, LLM über OpenAI direkt:

  cat mc_openai_direkt.py mc_lehrplan_enge_runde.py | docker compose run --rm --no-deps -T -e LLM_ENABLED=true \
      -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY -v <ordner>:/m64:ro \
      api python - /m64/themen.json

Die Themen als Datei: {"einfach": [...], "gruppe": [...], "aspekt": [...]}. Ergebnis als JSON nach JSON-START.
"""

# --- M64 prototype (not part of the service): part 2 with a further search word per variant ---
import dataclasses
import json
import re
import sys
import time

install()
import app.knowledge.topic_articles as topic_articles_module
import app.llm.prompts as prompts_module
import app.sources.lehrplan.matcher as matcher_module
from app.compendium.errors import TopicNotFoundError
from app.compendium.prepared import PreparedTopic
from app.domain.requests import GenerateRequest
from app.llm.deadline import Deadline
from app.main import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

topics = json.loads(open(sys.argv[1], encoding="utf-8").read())
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())

# question N names, besides its articles, the school form of the overview's title, curriculum terms and subjects
V4_USER = prompts_module.TOPIC_ARTICLES.user.replace(
    "Antworte so: {{",
    "Nenne außerdem unter „schulform“ die Schreibweise, unter der Schulen und Lehrpläne das Thema der Übersicht führen, "
    "wenn sie vom Titel abweicht (etwa „Brüche“ für Bruchrechnung, „Fotosynthese“ für Photosynthese), sonst leer; kein "
    "Oberbegriff. Nenne unter „lehrplan“ bis zu sechs kurze Suchbegriffe mit ein bis drei Wörtern, unter denen das "
    "Thema, wie es gefragt ist, in deutschen Lehrplänen steht: Fachbegriffe in der Schreibweise der Schule, Personen "
    "nur mit dem Nachnamen, keine Titel mit Klammerzusatz; bei einer Gruppe ihre wichtigsten Vertreter, bei einem "
    "Aspekt Begriffe, die den Aspekt selbst treffen; keine allgemeinen Wörter wie „Musik“, „Gruppe“, „Lernen“. Nenne "
    "unter „faecher“ die Schulfächer, in denen das Thema unterrichtet wird, mit ihrem üblichen Namen.\n"
    "Antworte so: {{",
).replace(
    '"deckt_ab": true}}',
    '"deckt_ab": true, "schulform": "<Wort>", "lehrplan": ["<Begriff>", ...], "faecher": ["<Fach>", ...]}}',
)
assert "schulform" in V4_USER and "faecher" in V4_USER
prompts_module.PROMPTS["topic_articles"] = dataclasses.replace(prompts_module.TOPIC_ARTICLES, version=4, user=V4_USER)
captured = {}
original_read = topic_articles_module.read_object


def reading(text):
    data = original_read(text)
    if isinstance(data, dict):
        captured["schulform"] = str(data.get("schulform") or "").strip()
        for key, size in (("lehrplan", 6), ("faecher", 4)):
            if isinstance(data.get(key), list):
                captured[key] = [str(t).strip() for t in data[key] if str(t).strip()][:size]
    return data


topic_articles_module.read_object = reading

# the further search words of a variant come first among the aliases and count only as whole words
EXTRA: list[str] = []
WHOLE: set[str] = set()
own_aliases = PreparedTopic.aliases.fget
PreparedTopic.aliases = property(lambda self: [*EXTRA, *own_aliases(self)])
original_boundary = matcher_module.boundary_keyword
LETTER = "[0-9A-Za-zÄÖÜäöüß]"


def standing(text, word):
    return re.search(f"(?<!{LETTER}){re.escape(word)}{LETTER}{{0,2}}(?!{LETTER})", text, re.I) is not None


def boundary(text, keywords):
    text = text.replace("\xad", "")
    for word in keywords:
        if word.casefold() in WHOLE:
            if standing(text, word):
                return word
        elif original_boundary(text, [word]):
            return word
    return None


matcher_module.boundary_keyword = boundary
keep = ("iri", "label", "bereich", "lehrplan", "bundesland", "schulfaecher", "keyword", "matched_in", "note")


def entries(part):
    return [{k: e.get(k) for k in keep} for e in part.entries] if part else []


rows = []
for kind, names in topics.items():
    for topic in names:
        for preset in ("balanced", "best-quality"):
            captured.clear()
            EXTRA.clear()
            WHOLE.clear()
            request = GenerateRequest(topic=topic, preset=preset, parts=["curricula"])
            deadline = Deadline(settings.request_time_limit_s)
            started = time.perf_counter()
            try:
                request, profile = service._admit(request, deadline)
                budget = service.open_budget(profile)
                _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
                prepared = service.prepare(request, deadline, choice)
            except TopicNotFoundError:
                rows.append({"kind": kind, "topic": topic, "preset": preset, "error": "404"})
                continue
            known = {k.casefold() for k in [prepared.title, *own_aliases(prepared), *prepared.subtopics] if k}
            school = captured.get("schulform", "")
            terms = [t for t in captured.get("lehrplan", []) if t.casefold() not in known]
            named_subjects = captured.get("faecher", [])
            subjects = [s for s in named_subjects if service.subjects.knows(s)]
            variants = {"heute": ([], None)}
            if school and school.casefold() not in known:
                variants["schulform"] = ([school], None)
            if terms:
                variants["begriffe"] = (terms, subjects or None)
            if topic.casefold() not in known:
                variants["thema"] = ([topic], None)
            row = {"kind": kind, "topic": topic, "preset": preset, "title": prepared.title, "schulform": school,
                   "terms": terms, "subjects_named": named_subjects, "subjects": subjects,
                   "covers": prepared.articles.covers if prepared.articles else None}
            own_subjects = prepared.subjects
            for name, (extra, narrow) in variants.items():
                EXTRA[:] = extra
                WHOLE.clear()
                WHOLE.update(word.casefold() for word in extra)
                prepared.subjects = narrow if narrow else own_subjects
                result = service._curricula_part(prepared, request, deadline)
                part = result.part
                row[name] = {"keywords": part.keywords if part else [], "entries": entries(part),
                             "summary": {k: (part.summary or {}).get(k) for k in ("matches", "bundled")} if part else {}}
            prepared.subjects = own_subjects
            row["seconds"] = round(time.perf_counter() - started, 1)
            row["tokens"] = getattr(budget, "spent", None)
            rows.append(row)
            print(f"# {preset} {topic}: schulform {school!r} terms {terms} subjects {subjects} "
                  f"variants {list(variants)} {row['seconds']} s", file=sys.stderr, flush=True)
print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
