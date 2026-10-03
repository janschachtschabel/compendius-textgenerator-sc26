"""Messskript M59 (03.10.2026): die KI-Schritte des Dienstes mit reasoning_effort low und none.

Jan: „prüfe wo man das reasoning überall abschalten kann um zeit und kosten zu sparen … wenn der qualitätsverfall
gering ist könnten wir reasoning deaktivieren“. Jeder Lauf nimmt den Aufwand aus LLM_REASONING_EFFORT; dasselbe
Skript läuft also je Schritt einmal mit low und einmal mit none, im Einmal-Container mit den Archiven, das LLM über
OpenAI direkt (mc_openai_direkt.py), frische Antworten (D70):

  cat mc_openai_direkt.py mc_reasoning.py | docker compose run --rm --no-deps -T -e LLM_ENABLED=true \
      -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY -e LLM_REASONING_EFFORT=none \
      api python - <schritt> <argumente>

Schritte:
- artikelwahl <profil> '<gold.json>': der Hauptartikel jeder Gold-Anfrage von eval/artikelwahl (die Liste der
  Anfragen als JSON), aufgelöst wie im Profil bis zum Korpus von Teil 1 (balanced: Frage N, best-quality: dazu die
  gründliche Wahl); richtig, wenn der Titel erwartet ist oder das Ziel einer Weiterleitung auf einen erwarteten Titel.
- zuordnung <weg>...: matcher=llm am Gold von eval/gold (das Verzeichnis nach /gold gebunden: -v <repo>/eval/gold:/gold),
  wie mc_llm_sparvarianten.py (M12): je Goldthema der Korpus nach den Regeln, davon die benoteten Absätze; Wege rules
  (hybrid_light), llm (50 Absätze à 400 Zeichen je Aufruf), llm_100x400, llm_50x250; macro- und micro-F1, Tokens,
  Sekunden. Dazu -e LLM_MAX_TOKENS_PER_REQUEST=400000 -e LLM_MAX_CONCURRENCY=4, damit kein Budget eingreift.
- lehrplan '<themen.json>': Teil 2 in best-quality an den Themen von M57 (je Art eine Liste), mit der LLM-Prüfung
  jedes Elements; je Element IRI, Stichwort, Fundort und Note, dazu Tokens und Sekunden.
- schreiben <variante>... -- <thema>...: Teil 1 in best-quality-generated (bqg) oder best-coverage-generated (bcg) wie
  mc_kompendium_profil.py (M48), mit dem Text für die blinden Bögen von mc_profilvergleich_boegen.py; die Variante heißt
  im Ergebnis <variante>-<aufwand>. Die Texte bleiben außerhalb des Repositorys.
- knoten '<materialien.json>' <profil>: POST /api/v2/knowledge mit node_id und repository je Material von
  eval/materialwahl (die Liste als JSON); der Hauptartikel gegen die akzeptierten Titel (Weiterleitungen eingeschlossen).
- entitaeten '<materialien.json>' <profil>: POST /api/v2/entities mit node_id und repository; die verknüpften Artikel
  je Material für die Noten von eval/entitaeten. Beide im Prozess über die API (TestClient), dazu -e RATE_LIMIT=0.
- knotenfrage '<materialien.json>' <läufe>: nur die Frage node_topic (D47) je Material, jedes einmal gelesen und dann
  <läufe>-mal mit low und mit none gefragt (beide Aufwände in einem Lauf, LLM_REASONING_EFFORT gilt hier nicht); der
  genannte Titel im Archiv nachgeschlagen (Weiterleitungen) und gegen die akzeptierten Titel geprüft.
- thema '<texte.json>': die Frage topic_wording (D72) für Texte, die eine Lehrkraft statt eines Themas schickt (die acht
  von M51); je Text die Formulierung, Tokens und Sekunden.
- profil <profil> -- <thema>...: eine ganze Anfrage (Teil 1 und 2) im Profil; je Thema die Zeiten der Schritte,
  Tokens und Rückfälle, kein Text (die Zeitersparnis bei Korpora in Produktionsgröße).
- qa '<themen.json>' <profil>: POST /api/v2/qa mit topic und profile (best-quality: Paare vom LLM aus Teil 1 nach den
  Regeln); je Thema die Paare, Tokens und Sekunden.

Ergebnis als JSON nach der Zeile JSON-START; Auswertung im Messprotokoll (M59).
"""

# --- M59: the LLM steps with reasoning_effort low and none ---
import json
import sys
import time

install()
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.llm.deadline import Deadline
from app.main import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
assert service.llm is not None, "LLM_ENABLED did not reach the settings"
EFFORT = service.llm.client.reasoning_effort
print(f"# reasoning_effort {EFFORT}", file=sys.stderr, flush=True)


def artikelwahl(preset, gold):
    wiki = service.registry.primary_archive
    rows = []
    for entry in gold:
        accepted = list(entry["erwartet"])
        for title in entry["erwartet"]:
            article = wiki.read_article(title)  # a redirect counts as its target (M35)
            if article is not None and article.title not in accepted:
                accepted.append(article.title)
        # part 1 up to the corpus: N names its articles while the corpus is built (D63)
        request = GenerateRequest(topic=entry["anfrage"], preset=preset, parts=["world"])
        deadline = Deadline(settings.request_timeout_s)
        started = time.perf_counter()
        budget = None
        try:
            request, profile = service._admit(request, deadline)
            budget = service.open_budget(profile)
            _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
            prepared = service.prepare(request, deadline, choice)
            resolution, named = prepared.resolution, prepared.articles
        except TopicNotFoundError as exc:
            resolution, named = exc.resolution, None
        rows.append({
            "anfrage": entry["anfrage"], "art": entry["art"], "datei": entry.get("datei"), "titel": resolution.title,
            "richtig": resolution.title in accepted, "methode": resolution.method,
            "uebersicht": named.overview if named else None, "gefunden": len(named.found) if named else 0,
            "n_fallback": named.fallback if named else None,
            "tokens": budget.used if budget is not None else 0, "sekunden": round(time.perf_counter() - started, 2),
        })
        print(f"# {preset} {entry['anfrage']}: {resolution.title} {rows[-1]['richtig']} {rows[-1]['sekunden']} s",
              file=sys.stderr, flush=True)
    return rows


def zuordnung(ways):
    from dataclasses import replace
    from pathlib import Path

    import app.matching.llm_assignment as llm_assignment
    from app.matching.eval import aggregate, align, evaluate, predictions_from_classification
    from app.matching.gold import load_gold

    sizes = {"llm": (50, 400), "llm_100x400": (100, 400), "llm_50x250": (50, 250)}
    pools = []
    for path in sorted(Path("/gold").glob("*.jsonl")):
        gold = load_gold(path)
        prepared = service.prepare(GenerateRequest(topic=gold.topic, parts=["world"]))  # the rules' corpus, as labelled
        alignment = align(gold, prepared.chunks)
        chunks = [c for c in prepared.chunks if c.chunk_id in alignment.gold_by_chunk]
        pools.append((gold, alignment, replace(prepared, chunks=chunks)))
    result = {}
    for way in ways:
        strategy = "hybrid_light" if way == "rules" else "llm"
        llm_assignment.BATCH_SIZE, llm_assignment.TEXT_CHARS = sizes.get(way, (50, 400))
        evals, per_topic, totals = [], {}, {"tokens": 0, "completion": 0, "calls": 0, "fallback": 0, "paragraphs": 0}
        started_all = time.perf_counter()
        for gold, alignment, pool in pools:
            started = time.perf_counter()
            matched = service.match(pool, strategy, 12_000)
            per_topic[gold.topic] = round(time.perf_counter() - started, 2)
            if matched.llm is not None:
                totals["tokens"] += matched.llm.total_tokens
                totals["completion"] += matched.llm.completion_tokens
                totals["calls"] += matched.llm.calls
                totals["fallback"] += matched.llm.fallback
                totals["paragraphs"] += matched.llm.paragraphs
            slot_keys = [slot.slot for slot in pool.template.content_slots()]
            classified = predictions_from_classification(matched.assignment.classified, pool.template)
            evals.append(evaluate(gold.topic, alignment.gold_by_chunk, classified, slot_keys, matcher=way))
        total = aggregate(evals)
        result[way] = {"macro_f1": total.macro_f1, "micro_f1": total.micro_f1, "misassigned": total.misassigned,
                       "assigned": total.assigned, **totals, "seconds": round(time.perf_counter() - started_all, 1),
                       "seconds_per_topic": per_topic}
        print(f"# {way}: macro {total.macro_f1:.3f} micro {total.micro_f1:.3f} tokens {totals['tokens']} "
              f"fallback {totals['fallback']} {result[way]['seconds']} s", file=sys.stderr, flush=True)
    return result


def lehrplan(topics):
    keep = ("iri", "keyword", "matched_in", "note")
    rows = []
    for kind, names in topics.items():
        for topic in names:
            started = time.perf_counter()
            try:
                result = service.generate(GenerateRequest(topic=topic, preset="best-quality", parts=["curricula"]))
            except TopicNotFoundError:
                rows.append({"kind": kind, "topic": topic, "error": "404"})
                continue
            part = result.curricula
            llm = result.audit.llm or {}
            rows.append({"kind": kind, "topic": topic, "article": result.resolution.title,
                         "keywords": part.keywords if part else [],
                         "entries": [{k: e.get(k) for k in keep} for e in (part.entries if part else [])],
                         "check": llm.get("curriculum_check"), "tokens": result.audit.llm_tokens,
                         "seconds": round(time.perf_counter() - started, 1)})
            print(f"# {kind} {topic}: {len(rows[-1]['entries'])} elements, {rows[-1]['seconds']} s",
                  file=sys.stderr, flush=True)
    return rows


def schreiben(variants, topics):
    import re

    from app.domain.models import SectionStatus

    presets = {"bqg": "best-quality-generated", "bcg": "best-coverage-generated"}
    content = (SectionStatus.LLM, SectionStatus.EXTRACTIVE, SectionStatus.LLM_SELECTED)
    mark = re.compile(r"<!--[^>]*-->\n?")
    rows = []
    for topic in topics:
        for variant in variants:
            started = time.perf_counter()
            result = service.generate(GenerateRequest(topic=topic, preset=presets[variant], parts=["world"]))
            took = time.perf_counter() - started
            sections = [s for s in result.sections if s.text and s.status in content]
            text = "\n\n".join(f"### {s.title}\n\n{mark.sub('', s.text)}" for s in sections)
            llm = result.audit.llm or {}
            rows.append({"topic": topic, "variant": f"{variant}-{EFFORT}", "s": round(took, 1),
                         "timings": result.audit.timings_ms, "heading": result.topic, "main": result.resolution.title,
                         "tokens": result.audit.llm_tokens, "blocks": len(sections),
                         "llm_blocks": sum(1 for s in sections if s.status is SectionStatus.LLM), "chars": len(text),
                         "fallbacks": (llm.get("generation") or {}).get("fallbacks"), "note": llm.get("note"),
                         "matching_fallbacks": (llm.get("matching") or {}).get("fallbacks"), "text": text})
            print(f"# {topic} {variant}-{EFFORT}: {took:.0f} s, {len(text)} chars, tokens {result.audit.llm_tokens}",
                  file=sys.stderr, flush=True)
    return rows


def _client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app(settings))


def knoten(materials, preset):
    wiki = service.registry.primary_archive
    rows = []
    with _client() as client:
        for entry in materials:
            accepted = list(entry.get("akzeptiert") or [])
            for title in entry.get("akzeptiert") or []:
                article = wiki.read_article(title)
                if article is not None and article.title not in accepted:
                    accepted.append(article.title)
            started = time.perf_counter()
            answer = client.post("/api/v2/knowledge", json={"node_id": entry["node_id"], "repository": entry["repository"],
                                                            "preset": preset, "max_chars": 2000})
            body = answer.json() if answer.status_code == 200 else {}
            title = (body.get("resolution") or {}).get("title")
            rows.append({"node_id": entry["node_id"], "art": entry.get("art"), "status": answer.status_code,
                         "titel": title, "richtig": title in accepted if accepted else title is None,
                         "node_article": body.get("node_article"), "sekunden": round(time.perf_counter() - started, 2)})
            print(f"# {entry['titel'][:50]}: {answer.status_code} {title} {rows[-1]['richtig']}", file=sys.stderr, flush=True)
    return rows


def entitaeten(materials, preset):
    rows = []
    with _client() as client:
        for entry in materials:
            started = time.perf_counter()
            answer = client.post("/api/v2/entities", json={"node_id": entry["node_id"], "repository": entry["repository"],
                                                           "preset": preset})
            body = answer.json() if answer.status_code == 200 else {}
            linked = sorted({e["article"]["title"] for e in body.get("entities") or [] if e.get("article")})
            rows.append({"node_id": entry["node_id"], "status": answer.status_code, "artikel": linked,
                         "methods": body.get("methods"), "llm": body.get("llm"), "llm_tokens": body.get("llm_tokens"),
                         "sekunden": round(time.perf_counter() - started, 2)})
            print(f"# {entry['titel'][:50]}: {answer.status_code} {len(linked)} articles", file=sys.stderr, flush=True)
    return rows


def thema(texts):
    from app.knowledge.article_choice import ArticleChoiceJob
    from app.knowledge.topic_wording import TopicWordingReport, word_topic

    rows = []
    for text in texts:
        job = ArticleChoiceJob(service.llm.client, service.llm.open_budget())
        report = TopicWordingReport(source="text", reason="measurement")
        started = time.perf_counter()
        worded = word_topic(job, text, report)
        rows.append({"text": text, "thema": worded, "fallback": report.fallback, "tokens": report.total_tokens,
                     "sekunden": round(time.perf_counter() - started, 2)})
        print(f"# {text[:50]} -> {worded}", file=sys.stderr, flush=True)
    return rows


def qa(topics, preset):
    rows = []
    with _client() as client:
        for topic in topics:
            started = time.perf_counter()
            answer = client.post("/api/v2/qa", json={"topic": topic, "preset": preset})
            body = answer.json() if answer.status_code == 200 else {"error": answer.text[:300]}
            rows.append({"topic": topic, "status": answer.status_code, "pairs": body.get("pairs"),
                         "method": body.get("method"), "llm_tokens": body.get("llm_tokens"),
                         "sekunden": round(time.perf_counter() - started, 2), "error": body.get("error")})
            print(f"# {topic}: {answer.status_code} {len(body.get('pairs') or [])} pairs", file=sys.stderr, flush=True)
    return rows


def profil(preset, topics):
    rows = []
    for topic in topics:
        started = time.perf_counter()
        result = service.generate(GenerateRequest(topic=topic, preset=preset))
        llm = result.audit.llm or {}
        rows.append({"topic": topic, "s": round(time.perf_counter() - started, 1), "timings": result.audit.timings_ms,
                     "tokens": result.audit.llm_tokens, "matching": {k: (llm.get("matching") or {}).get(k)
                                                                     for k in ("paragraphs", "fallbacks", "asked_again")},
                     "check": {k: (llm.get("curriculum_check") or {}).get(k) for k in ("rated", "dropped", "fallbacks")}})
        print(f"# {topic} {preset}: {rows[-1]['s']} s {result.audit.timings_ms}", file=sys.stderr, flush=True)
    return rows


def knotenfrage(materials, runs):
    from app.knowledge.article_choice import ArticleChoiceJob
    from app.knowledge.node_article import NodeArticleReport, ask_topic

    wiki = service.registry.primary_archive
    rows = []
    for entry in materials:
        accepted = set(entry.get("akzeptiert") or [])
        for title in entry.get("akzeptiert") or []:
            article = wiki.read_article(title)
            if article is not None:
                accepted.add(article.title)
        info, _ = service.read_node(entry["node_id"], entry["repository"])
        row = {"node_id": entry["node_id"], "art": entry.get("art"), "antworten": {}}
        for effort in ("low", "none"):
            service.llm.client.reasoning_effort = effort
            answers = []
            for _ in range(runs):
                report = NodeArticleReport()
                started = time.perf_counter()
                named = ask_topic(ArticleChoiceJob(service.llm.client, service.llm.open_budget()), info, report)
                title = named[0] if named else None
                article = wiki.read_article(title) if title else None
                found = article.title if article is not None else None
                correct = (found in accepted) if accepted else not title
                answers.append({"genannt": title, "artikel": found, "richtig": correct, "tokens": report.total_tokens,
                                "sekunden": round(time.perf_counter() - started, 2)})
            row["antworten"][effort] = answers
        rows.append(row)
        print(f"# {entry['titel'][:40]}: " + " | ".join(f"{e} {[a['genannt'] for a in row['antworten'][e]]}"
                                                       for e in ("low", "none")), file=sys.stderr, flush=True)
    return rows


step = sys.argv[1]
if step == "artikelwahl":
    result = artikelwahl(sys.argv[2], json.loads(sys.argv[3]))
elif step == "zuordnung":
    result = zuordnung(sys.argv[2:])
elif step == "lehrplan":
    result = lehrplan(json.loads(sys.argv[2]))
elif step == "knoten":
    result = knoten(json.loads(sys.argv[2]), sys.argv[3])
elif step == "entitaeten":
    result = entitaeten(json.loads(sys.argv[2]), sys.argv[3])
elif step == "profil":
    result = profil(sys.argv[2], sys.argv[4:])
elif step == "knotenfrage":
    result = knotenfrage(json.loads(sys.argv[2]), int(sys.argv[3]))
elif step == "thema":
    result = thema(json.loads(sys.argv[2]))
elif step == "qa":
    result = qa(json.loads(sys.argv[2]), sys.argv[3])
elif step == "schreiben":
    split = sys.argv.index("--")
    result = schreiben(sys.argv[2:split], sys.argv[split + 1 :])
else:
    raise SystemExit(f"unknown step {step}")
print("JSON-START")
print(json.dumps({"schritt": step, "aufwand": EFFORT, "ergebnis": result}, ensure_ascii=False))
