"""Messskript M80 (08.10.2026, Audit WA-02): die letzten Zahlen ohne Messung.

Das Audit vom 27.09.2026 (WA-02) fand Zahlen ohne Messung; M44 und M65 maßen die Faktoren der Zuordnungsregeln. Offen
blieben fünf, seit ``bb0ef74`` benannte Konstanten:

- ``MIN_SIMILARITY`` 0,1 (``app/matching/embeddings.py``) und ``MIN_CHAR_SIMILARITY`` 0,02 (``app/matching/lexical.py``):
  bis zu diesen Ähnlichkeiten ist ein Absatz kein Kandidat eines Bausteins;
- ``MIN_BLOCK_CHARS`` 300 (``app/compendium/world.py``): die Untergrenze des Anteils eines Bausteins;
- die Gewichte der Rangfolge verlinkter Artikel (``app/knowledge/related.py``): sie wählen den Korpus;
- ``MAX_LOOKUPS`` 40 (``app/synthesis/actors.py``): so viele verlinkte Artikel schlägt das Akteursverzeichnis nach.

Gemessen im Ablauf des Dienstes wie M44, M65 und M66: Korpus von ``llm-free``, Zuordnung ``hybrid_light`` samt
Model2Vec, ``target_length`` 12.000 wie ``compendium eval``. Die zehn Goldthemen am Gold (macro- und micro-F1 vor dem
Budget, macro-F1 im gedruckten Text), die 81 Themen von M65 ohne Gold (Absätze, die ihren Baustein wechseln; die
Nebenartikel des Korpus). Jedes Thema wird einmal vorbereitet; Schwellen und Untergrenze ändern nur die Zuordnung, die
Gewichte den Korpus, also bereitet jede ihrer Einstellungen die Themen neu vor. Die Akteure: je Thema ein Lauf von
``generate``, in dem das Verzeichnis mit jeder Grenze gebaut wird, aus denselben Quellen wie im Dienst.

Im Einmal-Container des Images mit dem Code eines Commits, ohne LLM:

  git archive <commit> app | tar -x -C <kopie>
  cat mc_schwellen.py | MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e LLM_ENABLED=false \
      -e PYTHONPATH=/src -v <kopie>/app:/src/app:ro -v <ordner>:/m80:ro -v <repo>/eval/gold:/gold:ro \
      api python - /m80/themen.json /gold > m80.txt

Die Themen als JSON-Liste. Ergebnis als JSON nach der Zeile JSON-START.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any

import app
from app.cli_common import cli_service
from app.compendium import world
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.knowledge import related
from app.matching import embeddings, lexical
from app.matching.eval import aggregate, align, evaluate, predictions_from_assignment, predictions_from_classification
from app.matching.gold import load_gold
from app.synthesis import actors, writer

STRATEGY = "hybrid_light"
TARGET_LENGTH = 12_000
THRESHOLDS = {
    (embeddings, "MIN_SIMILARITY"): (0.0, 0.05, 0.15, 0.2, 0.3),
    (lexical, "MIN_CHAR_SIMILARITY"): (0.0, 0.01, 0.05, 0.1),
}
SHORT_LENGTHS = (2_000, 3_000)  # below 3,600 characters the floor acts on sc26: ten blocks of equal weight
FLOORS = (0, 150, 300, 600)
WEIGHTS = {
    "STEM_IN_TITLE": (0.0, 24.0),
    "TOPIC_WORD_IN_TITLE": (0.0, 16.0),
    "NAMES_A_HEADING": (0.0, 14.0),
    "PER_MENTION": (0.0, 3.0),
    "MAX_MENTIONS": (4, 16),
    "ORDINARY_LENGTH": (0.0, 2.0),
}
# The shipped 40 first, as cold as in the service; then 160, whose first 40 lookups are warm, so the rest gives the
# cold cost of a lookup; then every limit warm
LOOKUPS = (("40_kalt", 40), ("160", 160), ("10", 10), ("20", 20), ("40", 40), ("80", 80))

print(f"Code: {app.__file__}", file=sys.stderr, flush=True)
topics: list[str] = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
golds = {gold.topic: gold for gold in map(load_gold, sorted(Path(sys.argv[2]).glob("*.jsonl")))}
service = cli_service(None)
if not service.settings.model2vec_path:
    raise SystemExit("MODEL2VEC_PATH ist leer: gemessen wird mit der Strategie der Profile, samt Model2Vec")
if service.llm is not None:
    raise SystemExit("Das LLM ist an: gemessen wird der Korpus von llm-free (LLM_ENABLED=false)")
print(f"{len(topics)} Themen, davon mit Gold: {sorted(set(topics) & set(golds))}", file=sys.stderr, flush=True)


def request(topic: str) -> GenerateRequest:
    template = {"template_id": golds[topic].template_id} if topic in golds else {}
    return GenerateRequest(topic=topic, parts=["world"], preset="llm-free", **template)


def prepare_all() -> dict[str, Any]:
    """The prepared topic and, with gold, its alignment; ``None`` for a topic the archives lack."""
    prepared_topics: dict[str, Any] = {}
    for topic in topics:
        try:
            prepared = service.prepare(request(topic))
        except TopicNotFoundError:
            prepared_topics[topic] = None
            continue
        prepared_topics[topic] = (prepared, align(golds[topic], prepared.chunks) if topic in golds else None)
    return prepared_topics


def assign_all(prepared_topics: dict[str, Any], target_length: int = TARGET_LENGTH) -> dict[str, Any]:
    """Per topic the classification, the printed assignment and its characters; over the gold topics the scores."""
    per_topic: dict[str, Any] = {}
    before_budget, printed_scores, by_topic = [], [], {}
    for topic, entry in prepared_topics.items():
        if entry is None:
            continue
        prepared, alignment = entry
        matched = service.match(prepared, STRATEGY, target_length).assignment
        printed = {item.chunk.chunk_id: slot for slot, items in matched.assigned.items() for item in items}
        chars = sum(len(item.chunk.text) for items in matched.assigned.values() for item in items)
        per_topic[topic] = (dict(matched.classified), printed, chars)
        if alignment is None:
            continue
        title = prepared.resolution.title or topic
        slot_keys = [slot.slot for slot in prepared.template.content_slots()]
        before = evaluate(
            title,
            alignment.gold_by_chunk,
            predictions_from_classification(matched.classified, prepared.template),
            slot_keys,
            matcher=STRATEGY,
        )
        shown = evaluate(
            title,
            alignment.gold_by_chunk,
            predictions_from_assignment(matched.assigned, prepared.template),
            slot_keys,
            matcher=STRATEGY,
        )
        before_budget.append(before)
        printed_scores.append(shown)
        by_topic[topic] = {"macro_f1": round(before.macro_f1, 3), "gedruckt_macro_f1": round(shown.macro_f1, 3)}
    whole, text = aggregate(before_budget), aggregate(printed_scores)
    gold = {
        "macro_f1": round(whole.macro_f1, 4),
        "micro_f1": round(whole.micro_f1, 4),
        "gedruckt_macro_f1": round(text.macro_f1, 4),
        "je_thema": by_topic,
    }
    return {"themen": per_topic, "gold": gold}


def moves(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Paragraphs whose block differs from ``base``, before the budget and in the printed text, and the characters."""
    moved = moved_printed = 0
    topics_moved = []
    for topic, (classified, printed, _) in base["themen"].items():
        other_classified, other_printed, _ = other["themen"][topic]
        here = sum(classified.get(cid) != other_classified.get(cid) for cid in classified.keys() | other_classified)
        shown = sum(printed.get(cid) != other_printed.get(cid) for cid in printed.keys() | other_printed)
        moved, moved_printed = moved + here, moved_printed + shown
        if here or shown:
            topics_moved.append(topic)
    return {
        "wechsel": moved,
        "wechsel_gedruckt": moved_printed,
        "themen_mit_wechsel": len(topics_moved),
        "zeichen_gedruckt": sum(chars for _, _, chars in other["themen"].values()),
        "gold": other["gold"],
    }


def with_value(module: Any, name: str, value: Any, run: Any) -> Any:
    shipped = getattr(module, name)
    setattr(module, name, value)
    try:
        return run()
    finally:
        setattr(module, name, shipped)


def side_articles(prepared_topics: dict[str, Any]) -> dict[str, list[str] | None]:
    return {
        topic: None if entry is None else [source.title for source in entry[0].sources if not source.is_primary]
        for topic, entry in prepared_topics.items()
    }


started = time.perf_counter()
results: dict[str, Any] = {"code": app.__file__}

# Actor directory first, before the many preparations below warm the archive: every limit from the sources of the
# service's own run, right after its preparation as in a request
shipped_collect = writer.collect_actors
records: list[dict[str, Any]] = []


def measured_collect(
    primary: Any, sources: Any, lookup: Any, max_lookups: int = actors.MAX_LOOKUPS, preferred_headings: Any = None
) -> Any:
    row: dict[str, Any] = {}
    for key, limit in LOOKUPS:
        asked: list[str] = []

        def counted(title: str) -> Any:
            asked.append(title)
            return lookup(title)

        begun = time.perf_counter()
        found = actors.collect_actors(
            primary, sources, counted, max_lookups=limit, preferred_headings=preferred_headings
        )
        row[key] = {
            "akteure": len(found),
            "nachgeschlagen": len(asked),
            "ms": round((time.perf_counter() - begun) * 1000, 1),
            "namen": [actor.name for actor in found],
        }
    records.append(row)
    return shipped_collect(primary, sources, lookup, max_lookups=max_lookups, preferred_headings=preferred_headings)


writer.collect_actors = measured_collect
results["akteure"] = {}
for topic in topics:
    records.clear()
    try:
        service.generate(request(topic))
    except TopicNotFoundError:
        continue
    if records:
        results["akteure"][topic] = records[0]
        counts = ", ".join(f"{key}: {records[0][key]['akteure']}" for key, _ in LOOKUPS)
        print(f"# {topic}: Akteure je Grenze {counts}", file=sys.stderr, flush=True)
writer.collect_actors = shipped_collect

# Thresholds and floor: one preparation, the assignment again per setting
prepared_topics = prepare_all()
results["vorbereiten_s"] = round(time.perf_counter() - started, 1)
paragraphs = sum(len(entry[0].chunks) for entry in prepared_topics.values() if entry is not None)
results["absaetze"] = paragraphs
print(f"vorbereitet in {results['vorbereiten_s']} s, {paragraphs} Absätze", file=sys.stderr, flush=True)
shipped = assign_all(prepared_topics)
results["ausgeliefert"] = moves(shipped, shipped)
print(f"ausgeliefert: {shipped['gold']['macro_f1']} / gedruckt {shipped['gold']['gedruckt_macro_f1']}", file=sys.stderr)
results["schwellen"] = {}
for (module, name), values in THRESHOLDS.items():
    for value in values:
        row = moves(shipped, with_value(module, name, value, lambda: assign_all(prepared_topics)))
        results["schwellen"][f"{name}={value}"] = row
        print(
            f"{name}={value}: {row['wechsel']}/{row['wechsel_gedruckt']}, gold {row['gold']['macro_f1']}"
            f" / gedruckt {row['gold']['gedruckt_macro_f1']}",
            file=sys.stderr,
            flush=True,
        )
results["untergrenze"] = {}
for length in SHORT_LENGTHS:
    at_length = with_value(world, "MIN_BLOCK_CHARS", world.MIN_BLOCK_CHARS, lambda: assign_all(prepared_topics, length))
    for floor in FLOORS:
        other = with_value(world, "MIN_BLOCK_CHARS", floor, lambda: assign_all(prepared_topics, length))
        row = moves(at_length, other)
        results["untergrenze"][f"{length}/{floor}"] = row
        print(
            f"Länge {length}, Untergrenze {floor}: {row['wechsel_gedruckt']} gedruckt anders, "
            f"{row['zeichen_gedruckt']} Zeichen, gold gedruckt {row['gold']['gedruckt_macro_f1']}",
            file=sys.stderr,
            flush=True,
        )

# Weights of the link ranking: the corpus again per setting
base_articles = side_articles(prepared_topics)
results["gewichte"] = {}
for name, values in WEIGHTS.items():
    for value in values:
        variant_topics = with_value(related, name, value, prepare_all)
        articles = side_articles(variant_topics)
        changed = {
            topic: {
                "weg": sorted(set(base) - set(articles[topic] or [])),
                "neu": sorted(set(articles[topic] or []) - set(base)),
            }
            for topic, base in base_articles.items()
            if base is not None and set(base) != set(articles[topic] or [])
        }
        gold = assign_all({topic: entry for topic, entry in variant_topics.items() if topic in golds})["gold"]
        results["gewichte"][f"{name}={value}"] = {
            "themen_mit_anderem_korpus": len(changed),
            "korpus": changed,
            "gold": gold,
        }
        print(
            f"{name}={value}: {len(changed)} Korpora anders, gold {gold['macro_f1']} / gedruckt "
            f"{gold['gedruckt_macro_f1']}",
            file=sys.stderr,
            flush=True,
        )
again = side_articles(prepare_all())
results["korpus_wiederholt_gleich"] = again == base_articles  # the parse cache leaves no trace between runs


results["sekunden"] = round(time.perf_counter() - started, 1)
print("JSON-START")
print(json.dumps(results, ensure_ascii=False))
