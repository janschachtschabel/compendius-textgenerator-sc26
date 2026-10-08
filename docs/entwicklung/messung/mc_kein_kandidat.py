"""Messskript M63 (03.10.2026, Audit A01): wie oft die KI-Artikelwahl „kein Kandidat passt“ sagt, und was dann bleibt.

A01: Antwortet die Artikelwahl (article_choice=llm, D35) mit „wahl“: 0 und ohne Titel, bleibt bisher der Artikel der
Regeln stehen. Jan: „wenn die ki sagt der artikel passt nicht sollten sie wahrscheinlich raus weil wir sonst falsche
artikel risikieren oder ? prüfe das mit tests nach.“ Das Skript löst jedes Thema auf, wie das Profil es tut (Frage N,
dann die Regeln, dann die Wahl unter den Kandidaten der Regeln), ohne den Korpus zu bauen, und hält je Thema fest, ob
die Wahl gefragt wurde, welche Kandidaten sie sah, was sie antwortete und welcher Artikel blieb; bei „kein Kandidat
passt“ dazu den Anfang des behaltenen Artikels und der Übersicht von N für die blinden Noten. Einmal-Container mit den
Archiven, LLM über OpenAI direkt (mc_openai_direkt.py), frische Antworten:

  cat mc_openai_direkt.py mc_kein_kandidat.py | docker compose run --rm --no-deps -T -e LLM_ENABLED=true \
      -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY -v <ordner>:/m63:ro \
      api python - <profil> /m63/themen.json

Die Themen als Datei mit einer JSON-Liste mit topic, set, subject, expected (die akzeptierten Titel der
Gold-Anfragen) und kind.
Ergebnis als JSON nach der Zeile JSON-START; Auswertung im Messprotokoll (M63).
"""

# --- M63: what the article choice answers, and the article that stays when nothing fits ---
import json
import sys
import time

install()
import app.knowledge.article_choice as article_choice
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.knowledge.main_article import choose_main_article
from app.llm.deadline import Deadline
from app.main import build_registry, build_service
from app.settings import get_settings
from app.sources.zim.topic_rules import opening
from app.templates.manager import TemplateManager

NOTHING_FITS = "kein Kandidat passt, kein Titel genannt"  # the fallback of the verdict before A01
preset = sys.argv[1]
topics = json.loads(open(sys.argv[2], encoding="utf-8").read())
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
wiki = service.registry.primary_archive
seen = {}
original_call = article_choice.LlmArticleChooser.__call__


def calling(self, candidates):
    answer = original_call(self, candidates)
    seen["candidates"] = [title for title, _ in candidates]
    seen["answer"] = answer
    return answer


article_choice.LlmArticleChooser.__call__ = calling


def beginning(title):
    """The opening of an article as the chooser sees a candidate, and its title after redirects."""
    article = wiki.read_article(title) if title else None
    if article is None:
        return None, None
    parsed = wiki.parse(article)
    return parsed.title, opening(parsed.text)


rows = []
for entry in topics:
    seen.clear()
    started = time.perf_counter()
    row = {key: entry.get(key) for key in ("topic", "set", "subject", "kind", "expected")}
    try:
        request = GenerateRequest(topic=entry["topic"], subject=entry.get("subject"), preset=preset, parts=["world"])
        deadline = Deadline(settings.request_time_limit_s)
        request, profile = service._admit(request, deadline)
        budget = service.open_budget(profile)
        _, _, job = service.article_choice_job(request.article_choice, deadline, budget)
        main = choose_main_article(service.registry, service.subjects, request.topic, [], subject=request.subject,
                                   job=job)
    except TopicNotFoundError as exc:
        row["error"] = f"404 {exc}"
        rows.append(row)
        continue
    except Exception as exc:  # a subject the catalogue refuses, say: the row says why
        row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        continue
    resolution, choice, named = main.resolution, main.choice, main.articles
    row.update({
        "title": resolution.title, "method": resolution.method, "confident": resolution.confident,
        "alternatives": resolution.alternatives,
        "asked": bool(choice and choice.offered), "candidates": seen.get("candidates"),
        "answer": list(seen["answer"]) if "answer" in seen else None,
        "choice_fallback": choice.fallback if choice else None, "choice_named": choice.named if choice else None,
        # before A01 the verdict stood as a fallback, since then as rejected
        "nothing_fits": bool(choice) and (choice.fallback == NOTHING_FITS or getattr(choice, "rejected", False)),
        "overview": named.overview if named else None, "found": named.found if named else [],
        "n_fallback": named.fallback if named else None,
        "seconds": round(time.perf_counter() - started, 2),
    })
    if row["expected"]:
        accepted = set(row["expected"])
        for title in row["expected"]:
            target, _ = beginning(title)  # a redirect counts as its target (M35)
            if target:
                accepted.add(target)
        row["right"] = resolution.title in accepted
    if row["nothing_fits"]:
        row["kept"] = beginning(resolution.title)
        row["overview_article"] = beginning(row["overview"]) if row["overview"] else None
    rows.append(row)
    print(f"# {preset} {entry['topic']}: {resolution.title} asked={row['asked']} {row['choice_fallback']} "
          f"{row['seconds']} s", file=sys.stderr, flush=True)
print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
