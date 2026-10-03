"""Messskript M65 (03.10.2026, Audit WA-02): ob drei Faktoren der Zuordnungsregeln außerhalb des Golds etwas ändern.

M44 maß die sechs Faktoren von ``_score_candidate`` an den zehn Goldthemen: ``SUBAREA_BOOST`` und
``PREFERRED_SOURCE_BOOST`` änderten dort nichts, ``EXCLUSION_FACTOR`` kostete etwas (macro-F1 0,466 ohne ihn statt
0,459). Zehn Themen sind wenig. Dieses Skript zählt an vielen Themen ohne Gold, wie viele Absätze ihren Baustein
wechseln, wenn ein Faktor 1,0 ist - vor dem Budget (die Zuordnung) und im gedruckten Text -, und hält die gewechselten
Absätze fest (Überschrift, Baustein vorher und nachher, Textanfang), damit sie benotet werden können. Korpus von
``llm-free`` und Strategie ``hybrid_light`` samt Model2Vec wie M44, im Einmal-Container mit den Archiven, ohne LLM:

  cat mc_policy_faktoren_breit.py | docker compose run --rm --no-deps -T -v <ordner>:/m65:ro api python - \
      /m65/themen.json > m65.txt

Die Themen als JSON-Liste. Ergebnis als JSON nach der Zeile JSON-START.
"""

import json
import sys
import time

from app.cli_common import cli_service
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.matching import policy

STRATEGY = "hybrid_light"
TARGET_LENGTH = 12_000
FACTORS = ("SUBAREA_BOOST", "PREFERRED_SOURCE_BOOST", "EXCLUSION_FACTOR")

topics = json.loads(open(sys.argv[1], encoding="utf-8").read())
service = cli_service(None)
if not service.settings.model2vec_path:
    raise SystemExit("MODEL2VEC_PATH ist leer: gemessen wird mit der Strategie der Profile, samt Model2Vec")


def assignment(prepared):
    matched = service.match(prepared, STRATEGY, TARGET_LENGTH).assignment
    printed = {item.chunk.chunk_id: slot for slot, items in matched.assigned.items() for item in items}
    return dict(matched.classified), printed


rows, started = [], time.perf_counter()
for topic in topics:
    try:
        prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    except TopicNotFoundError:
        rows.append({"topic": topic, "error": "404"})
        continue
    slot_key = {slot.id: slot.slot for slot in prepared.template.slots}
    chunks = {chunk.chunk_id: chunk for chunk in prepared.chunks}
    shipped = assignment(prepared)
    row = {"topic": topic, "title": prepared.resolution.title, "paragraphs": len(prepared.chunks)}
    for name in FACTORS:
        value = getattr(policy, name)
        setattr(policy, name, 1.0)
        try:
            neutral = assignment(prepared)
        finally:
            setattr(policy, name, value)
        moved = [cid for cid in chunks if shipped[0].get(cid) != neutral[0].get(cid)]
        moved_printed = [cid for cid in chunks if shipped[1].get(cid) != neutral[1].get(cid)]
        row[name] = {
            "wechsel": len(moved),
            "wechsel_gedruckt": len(moved_printed),
            "absaetze": [
                {"id": cid, "ueberschrift": chunks[cid].full_heading, "quelle": chunks[cid].source_id,
                 "mit": slot_key.get(shipped[0].get(cid)), "ohne": slot_key.get(neutral[0].get(cid)),
                 "gedruckt_mit": slot_key.get(shipped[1].get(cid)), "gedruckt_ohne": slot_key.get(neutral[1].get(cid)),
                 "text": " ".join(chunks[cid].text.split())[:300]}
                for cid in sorted(set(moved) | set(moved_printed))
            ],
        }
    rows.append(row)
    print(f"# {topic}: " + ", ".join(f"{n} {row[n]['wechsel']}/{row[n]['wechsel_gedruckt']}" for n in FACTORS),
          file=sys.stderr, flush=True)
print("JSON-START")
print(json.dumps({"seconds": round(time.perf_counter() - started, 1), "rows": rows}, ensure_ascii=False))
