"""Messskript M69 (04.10.2026): wie oft der Hauptartikel den Korpusdeckel füllt und Nebenquellen verdrängt.

Audit 2026-10-03, F02: ``segment_corpus`` (app/compendium/corpus.py) füllt ``CORPUS_MAX_CHUNKS`` (Vorgabe 400) nach
Rängen - Hauptartikel und Artikel desselben Themas zuerst, dann Materialien, dann Nebenartikel -, und innerhalb einer
Quelle die ersten Absätze. Ein Hauptartikel mit mehr Absätzen als der Deckel ließe keiner Nebenquelle Platz. Wie oft
das bei echten Themen vorkommt, zählt dieses Skript im Ablauf des Dienstes, ohne LLM (Korpus von ``llm-free``): je
Thema die Absätze je Rang vor dem Deckel, was jeder Rang bekam, wie viele Nebenquellen leer ausgingen.

  cat mc_korpusdeckel.py | docker compose run --rm --no-deps -T -v <ordner mit themen.json>:/x:ro api \
      python - /x/themen.json

``themen.json`` ist eine Liste von Themen (Text oder Objekt mit ``topic`` und ``subject``). Ergebnis als JSON nach
der Zeile JSON-START.
"""

import json
import sys

import app.compendium.corpus as corpus
from app.domain.requests import GenerateRequest
from app.wiring import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
seen = {"ranks": []}
original_share = corpus._share
original_segment = corpus.segment_corpus


def sharing(indexes, needs, budget):
    shares = original_share(indexes, needs, budget)
    seen["ranks"].append({"needs": list(needs), "budget": budget, "allowed": [shares[i] for i in indexes]})
    return shares


def segmenting(sources, lexicon, max_chunks):
    seen["origins"] = [source.origin for source in sources]
    seen["titles"] = [source.title for source in sources]
    return original_segment(sources, lexicon, max_chunks)


corpus._share = sharing
corpus.segment_corpus = segmenting
import app.service as service_module  # noqa: E402

service_module.segment_corpus = segmenting

entries = json.loads(open(sys.argv[1], encoding="utf-8").read())
rows = []
for entry in entries:
    topic = entry if isinstance(entry, str) else entry["topic"]
    subject = None if isinstance(entry, str) else entry.get("subject")
    seen.clear()
    seen["ranks"] = []
    try:
        prepared = service.prepare(
            GenerateRequest(topic=topic, subject=subject, parts=["world"], preset="llm-free")
        )
    except Exception as exc:  # a measurement records the failure and goes on
        rows.append({"topic": topic, "error": f"{type(exc).__name__}: {exc}"[:200]})
        continue
    # the ranks in the order segment_corpus filled them, each source with its origin
    order = sorted(range(len(seen["origins"])), key=lambda i: corpus.ORIGIN_PRIORITY.get(seen["origins"][i], 99))
    rows.append(
        {
            "topic": topic,
            "main": prepared.resolution.title,
            "max_chunks": settings.corpus_max_chunks,
            "origins": seen["origins"],
            "titles": seen["titles"],
            "ranks": seen["ranks"],
            "truncated": prepared.chunks_truncated,
            "chunks": len(prepared.chunks),
            "kept_sources": len(prepared.sources),
        }
    )
    print(f"# {topic}: {len(prepared.chunks)} Absätze, {prepared.chunks_truncated} abgeschnitten", file=sys.stderr)

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
