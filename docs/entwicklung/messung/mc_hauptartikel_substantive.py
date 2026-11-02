"""Messskript: zwei Anregungen aus dem Themenbaum-Generator (topic-tree-llm-free), gemessen im Ablauf des Dienstes.

1. Hauptartikel-Verweise: Ein Link, den der Hauptartikel als "→ Hauptartikel: X" unter einem Abschnitt nennt, bekommt
   in der Rangfolge der verlinkten Artikel (``app/knowledge/related.py``) ein Zusatzgewicht; Werte 7, 14, 24.
2. Model2Vec mit Substantiven: Absätze und Bausteine gehen nur mit ihren Substantiven (großgeschrieben, ohne
   Stoppwörter) an Model2Vec; Variante "ohne Stoppwörter" dazwischen. BM25 und Zeichen-n-Gramme bleiben wie sie sind.

Aufbau wie M80 (``mc_schwellen.py``): Korpus von ``llm-free``, Zuordnung ``hybrid_light`` samt Model2Vec,
``target_length`` 12.000, die 81 Themen von M80 (darunter die zehn Goldthemen); macro- und micro-F1 vor dem Budget,
macro-F1 im gedruckten Text, an den übrigen Themen die Absätze, die ihren Baustein wechseln, und die Nebenartikel.
Am Dienst wird nichts geändert: beide Varianten ersetzen eine Funktion nur in diesem Prozess.

Aufruf im Repo (venv), ohne LLM:
  LLM_ENABLED=false HF_HUB_OFFLINE=1 PYTHONPATH=. python mc_hauptartikel_substantive.py themen.json eval/gold out.json
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from libzim.reader import Archive

import app
from app.cli_common import cli_service
from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.knowledge import corpus_sources, related
from app.matching import base, embeddings
from app.matching.eval import aggregate, align, evaluate, predictions_from_assignment, predictions_from_classification
from app.matching.gold import load_gold

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
M2V = "JanSchachtschabel/m2v-gte-256-edu"
STRATEGY = "hybrid_light"
TARGET_LENGTH = 12_000
HAUPTARTIKEL_WEIGHTS = (7.0, 14.0, 24.0)

# Der allgemeine Teil der Stoppwortliste des Themenbaum-Generators (themenbaum/contents.py); dessen Wörter aus
# Materialbeschreibungen (Physik, Experiment, Arbeitsblatt ...) bleiben weg: in Wikipedia-Absätzen sind sie Fachwörter
STOP = set("""
aber alle allem allen aller alles als also am an ander andere anderem anderen anderer anderes anders auch auf aus
bei beim bin bis bist da dabei dadurch dafür dagegen daher damit dann daran darauf daraus darin darum darüber das
dass dasselbe davon dazu dem den denen denn der deren des deshalb dessen die dies diese diesem diesen dieser dieses
doch dort du durch ein eine einem einen einer eines einige einigen einmal er es etwa etwas euch euer für gegen
geht gibt hat hatte haben hier hin hinter ich ihm ihn ihnen ihr ihre ihrem ihren ihrer ihres im in indem ins ist
ja je jede jedem jeden jeder jedes jetzt kann kein keine können könnte machen man manche mehr mein mit muss nach
neben nicht nichts noch nun nur ob oder ohne sehr sein seine seinem seinen seiner sich sie sind so solche soll
sollen sondern sowie über um und uns unser unter viel viele vom von vor wann war waren warum was weil weiter
welche welchem welchen welcher welches wenn wer werden wie wieder will wir wird wo wobei wurde wurden zu zum zur
zwar zwischen sowohl besonders bereits dabei jeweils dafür hierbei zudem außerdem anschließend eigene eigenen
""".split())
WORD = re.compile(r"[\w-]+")


def nouns(text: str) -> str:
    return " ".join(w for w in WORD.findall(text) if w[:1].isupper() and w.lower() not in STOP and len(w) > 2)


def no_stop(text: str) -> str:
    return " ".join(w for w in WORD.findall(text) if w.lower() not in STOP and len(w) > 2)


topics: list[str] = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
golds = {gold.topic: gold for gold in map(load_gold, sorted(Path(sys.argv[2]).glob("*.jsonl")))}
service = cli_service(ZIMS)
service.settings.model2vec_path = M2V
if service.llm is not None:
    raise SystemExit("Das LLM ist an: gemessen wird der Korpus von llm-free (LLM_ENABLED=false)")
wikipedia = Archive(ZIMS[0])
print(f"Code: {app.__file__}; {len(topics)} Themen, Gold: {len(set(topics) & set(golds))}", file=sys.stderr, flush=True)


def request(topic: str) -> GenerateRequest:
    template = {"template_id": golds[topic].template_id} if topic in golds else {}
    return GenerateRequest(topic=topic, parts=["world"], preset="llm-free", **template)


def prepare_all() -> dict[str, Any]:
    prepared_topics: dict[str, Any] = {}
    for topic in topics:
        try:
            prepared = service.prepare(request(topic))
        except TopicNotFoundError:
            prepared_topics[topic] = None
            continue
        prepared_topics[topic] = (prepared, align(golds[topic], prepared.chunks) if topic in golds else None)
    return prepared_topics


def assign_all(prepared_topics: dict[str, Any]) -> dict[str, Any]:
    per_topic: dict[str, Any] = {}
    before_budget, printed_scores, by_topic = [], [], {}
    for topic, entry in prepared_topics.items():
        if entry is None:
            continue
        prepared, alignment = entry
        matched = service.match(prepared, STRATEGY, TARGET_LENGTH).assignment
        printed = {item.chunk.chunk_id: slot for slot, items in matched.assigned.items() for item in items}
        chars = sum(len(item.chunk.text) for items in matched.assigned.values() for item in items)
        per_topic[topic] = (dict(matched.classified), printed, chars)
        if alignment is None:
            continue
        title = prepared.resolution.title or topic
        slot_keys = [slot.slot for slot in prepared.template.content_slots()]
        before = evaluate(title, alignment.gold_by_chunk,
                          predictions_from_classification(matched.classified, prepared.template), slot_keys,
                          matcher=STRATEGY)
        shown = evaluate(title, alignment.gold_by_chunk,
                         predictions_from_assignment(matched.assigned, prepared.template), slot_keys, matcher=STRATEGY)
        before_budget.append(before)
        printed_scores.append(shown)
        by_topic[topic] = {"macro_f1": round(before.macro_f1, 3), "gedruckt_macro_f1": round(shown.macro_f1, 3)}
    whole, text = aggregate(before_budget), aggregate(printed_scores)
    gold = {"macro_f1": round(whole.macro_f1, 4), "micro_f1": round(whole.micro_f1, 4),
            "gedruckt_macro_f1": round(text.macro_f1, 4), "je_thema": by_topic}
    return {"themen": per_topic, "gold": gold}


def moves(base_run: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    moved = moved_printed = 0
    topics_moved = []
    for topic, (classified, printed, _) in base_run["themen"].items():
        if topic not in other["themen"]:
            continue
        other_classified, other_printed, _ = other["themen"][topic]
        here = sum(classified.get(cid) != other_classified.get(cid) for cid in classified.keys() | other_classified)
        shown = sum(printed.get(cid) != other_printed.get(cid) for cid in printed.keys() | other_printed)
        moved, moved_printed = moved + here, moved_printed + shown
        if here or shown:
            topics_moved.append(topic)
    return {"wechsel": moved, "wechsel_gedruckt": moved_printed, "themen_mit_wechsel": len(topics_moved),
            "zeichen_gedruckt": sum(chars for _, _, chars in other["themen"].values()), "gold": other["gold"]}


def side_articles(prepared_topics: dict[str, Any]) -> dict[str, list[str] | None]:
    return {topic: None if entry is None else [s.title for s in entry[0].sources if not s.is_primary]
            for topic, entry in prepared_topics.items()}


# -- 1. Hauptartikel-Verweise ---------------------------------------------------------------------------------------
_TARGETS: dict[str, set[str]] = {}
_BLOCK = re.compile(r'<div class="hauptartikel"[^>]*>.*?</div>', re.S)
_TITLE = re.compile(r'title="([^"]+)"')


def hauptartikel_targets(title: str) -> set[str]:
    """The lower-cased titles the article names as "→ Hauptartikel: X" (dewiki in mwoffliner: div.hauptartikel)."""
    if title not in _TARGETS:
        found: set[str] = set()
        try:
            entry = wikipedia.get_entry_by_title(title)
            while entry.is_redirect:
                entry = entry.get_redirect_entry()
            html = bytes(entry.get_item().content).decode("utf-8")
            found = {t.lower() for block in _BLOCK.findall(html) for t in _TITLE.findall(block) if t != "siehe"}
        except KeyError:
            pass
        _TARGETS[title] = found
    return _TARGETS[title]


def ranking_with_hauptartikel(weight: float) -> Any:
    """rank_related_candidates of app/knowledge/related.py with one more term: a Hauptartikel target adds ``weight``."""

    def rank(main: Any, candidates: list[str]) -> list[str]:
        main_title = main.title.lower()
        content_lower = "\n".join(p.text for s in main.sections for p in s.paragraphs).lower()
        headings = {h.lower() for s in main.sections for h in s.path}
        stems = related.title_stems(main.title)
        topic_words = set(related.title_words(main.title))
        targets = hauptartikel_targets(main.title)
        scored: list[tuple[float, str]] = []
        seen: set[str] = set()
        for raw in candidates:
            link = raw.strip().replace("_", " ")
            key = link.lower()
            if not link or key in seen or key == main_title:
                continue
            seen.add(key)
            if related.is_blacklisted(key, topic=main_title):
                continue
            score = 0.0
            if any(stem in key for stem in stems):
                score += related.STEM_IN_TITLE
            elif any(w in key for w in topic_words):
                score += related.TOPIC_WORD_IN_TITLE
            if any(key == h or key in h or h in key for h in headings):
                score += related.NAMES_A_HEADING
            if len(link) >= 3:
                score += min(content_lower.count(key), related.MAX_MENTIONS) * related.PER_MENTION
            if 4 <= len(link) <= 40:
                score += related.ORDINARY_LENGTH
            if key in targets:
                score += weight
            if score > 0:
                scored.append((score, link))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [title for _, title in scored]

    return rank


def target_share(prepared_topics: dict[str, Any]) -> dict[str, int]:
    """How many Hauptartikel targets of the main articles stand in the corpus."""
    total = inside = 0
    for entry in prepared_topics.values():
        if entry is None:
            continue
        prepared = entry[0]
        primary = next((s for s in prepared.sources if s.is_primary), None)
        if primary is None:
            continue
        targets = hauptartikel_targets(primary.title)
        corpus = {s.title.lower() for s in prepared.sources}
        total += len(targets)
        inside += len(targets & corpus)
    return {"ziele": total, "im_korpus": inside}


started = time.perf_counter()
results: dict[str, Any] = {"code": app.__file__}
shipped_rank = corpus_sources.rank_related_candidates

baseline_prepared = prepare_all()
baseline = assign_all(baseline_prepared)
baseline_sides = side_articles(baseline_prepared)
results["ausgeliefert"] = {**moves(baseline, baseline), "hauptartikel": target_share(baseline_prepared)}
print("ausgeliefert", results["ausgeliefert"]["gold"]["macro_f1"], results["ausgeliefert"]["gold"]["gedruckt_macro_f1"],
      results["ausgeliefert"]["hauptartikel"], f"{time.perf_counter() - started:.0f} s", file=sys.stderr, flush=True)

# control: the shipped ranking once more through the same path must give the same corpora
corpus_sources.rank_related_candidates = ranking_with_hauptartikel(0.0)
control = side_articles(prepare_all())
corpus_sources.rank_related_candidates = shipped_rank
results["kontrolle_gleich"] = control == baseline_sides

results["hauptartikel"] = {}
for weight in HAUPTARTIKEL_WEIGHTS:
    corpus_sources.rank_related_candidates = ranking_with_hauptartikel(weight)
    try:
        prepared_topics = prepare_all()
    finally:
        corpus_sources.rank_related_candidates = shipped_rank
    sides = side_articles(prepared_topics)
    changed = [t for t in topics if sides.get(t) != baseline_sides.get(t)]
    out = sum(len(set(baseline_sides[t] or []) - set(sides[t] or [])) for t in changed)
    run = assign_all(prepared_topics)
    results["hauptartikel"][str(weight)] = {
        **moves(baseline, run), "korpora_anders": len(changed), "nebenartikel_heraus": out,
        "hauptartikel": target_share(prepared_topics),
        "beispiele": {t: {"vorher": baseline_sides[t], "nachher": sides[t]} for t in changed[:6]},
    }
    print("hauptartikel", weight, run["gold"]["macro_f1"], run["gold"]["gedruckt_macro_f1"], len(changed),
          f"{time.perf_counter() - started:.0f} s", file=sys.stderr, flush=True)

results["model2vec"] = {}
shipped_chunk, shipped_slot = embeddings.chunk_representation, embeddings.slot_representation
for name, prep in (("substantive", nouns), ("ohne_stoppwoerter", no_stop)):
    embeddings.chunk_representation = lambda chunk, prep=prep: prep(shipped_chunk(chunk))
    embeddings.slot_representation = lambda slot, prep=prep: prep(shipped_slot(slot))
    try:
        run = assign_all(baseline_prepared)
    finally:
        embeddings.chunk_representation, embeddings.slot_representation = shipped_chunk, shipped_slot
    results["model2vec"][name] = moves(baseline, run)
    print("model2vec", name, run["gold"]["macro_f1"], run["gold"]["gedruckt_macro_f1"],
          f"{time.perf_counter() - started:.0f} s", file=sys.stderr, flush=True)
# control: the shipped representations once more
results["model2vec"]["kontrolle"] = moves(baseline, assign_all(baseline_prepared))

results["sekunden"] = round(time.perf_counter() - started)
Path(sys.argv[3]).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print("geschrieben", sys.argv[3], file=sys.stderr, flush=True)
