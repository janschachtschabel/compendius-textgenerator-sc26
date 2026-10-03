"""Messskript M66 (03.10.2026, Audit KO-11): die Themenstämme vereinheitlichen - was ändert sich am Korpus und am Gold?

KO-11: Drei Regeln bildeten den Stamm eines Themas: ``topic_stem`` und ``TopicMention`` für die Prüfung, ob ein
Absatz oder ein Treffer vom Thema handelt (erstes Titelwort ohne Artikel, kurze Wörter als ganzes Wort, KO-29),
``_stems`` in ``app/knowledge/related.py`` für die Rangfolge der verlinkten Nebenartikel (jedes Titelwort ab vier
Buchstaben, bis fünf Buchstaben ganz) und ``title[:5]`` im Glossar. Das Skript baut den Korpus von ``llm-free`` für
jedes Thema und schreibt die Quellen je Thema (Titel und Herkunft) und, mit Gold, macro- und micro-F1 der Zuordnung
(``hybrid_light`` samt Model2Vec, wie M44). Es läuft zweimal im Einmal-Container: mit dem Code des Images (vorher) und
mit dem Code des Arbeitsstands (nachher, ``-v <repo>/app:/src/app:ro -e PYTHONPATH=/src``):

  cat mc_themenstaemme.py | docker compose run --rm --no-deps -T -v <ordner>:/m66:ro -v <repo>/eval/gold:/gold:ro \
      api python - /m66/themen.json > vorher.txt

Ergebnis als JSON nach der Zeile JSON-START.
"""

import json
import sys
from pathlib import Path

from app.cli_common import cli_service
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.matching.eval import aggregate, align, evaluate, predictions_from_classification
from app.matching.gold import load_gold

topics = json.loads(open(sys.argv[1], encoding="utf-8").read())
service = cli_service(None)
corpora = {}
for topic in topics:
    try:
        prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    except TopicNotFoundError:
        corpora[topic] = None
        continue
    corpora[topic] = [[source.title, source.origin] for source in prepared.sources]
    print(f"# {topic}: {len(prepared.sources)} Quellen", file=sys.stderr, flush=True)

evals = []
for path in sorted(Path("/gold").glob("*.jsonl")):
    gold = load_gold(path)
    prepared = service.prepare(GenerateRequest(topic=gold.topic, template_id=gold.template_id))
    alignment = align(gold, prepared.chunks)
    matched = service.match(prepared, "hybrid_light", 12_000)
    slot_keys = [slot.slot for slot in prepared.template.content_slots()]
    classified = predictions_from_classification(matched.assignment.classified, prepared.template)
    evals.append(evaluate(gold.topic, alignment.gold_by_chunk, classified, slot_keys, matcher="hybrid_light"))
total = aggregate(evals)
print("JSON-START")
print(json.dumps({"korpus": corpora, "gold": {"macro_f1": round(total.macro_f1, 4), "micro_f1": round(total.micro_f1, 4),
                  "je_thema": {e.topic: round(e.macro_f1, 4) for e in evals}}}, ensure_ascii=False))
