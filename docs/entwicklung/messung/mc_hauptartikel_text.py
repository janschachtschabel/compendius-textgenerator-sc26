"""Messskript zu M92: der gedruckte Text vorher und nachher für einzelne Themen (Variante schutz_24_max3).

Je Thema der Korpus beider Läufe und je Baustein die gedruckten Absätze, die wegfallen und die hinzukommen, mit ihrem
Quellartikel; Ausgabe als Text auf stdout (mit Auszügen der Absätze, nicht für das Repository).

Aufruf im Repo (venv), ohne LLM:
  LLM_ENABLED=false HF_HUB_OFFLINE=1 PYTHONPATH=. python mc_hauptartikel_text.py themen.json eval/gold "<Thema>"…
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




def guarded_ranking(weight: float, cap: int | None) -> Any:
    """Idea 1: candidates with a stem of the topic in their title keep their place in the shipped ranking, targets among
    them get nothing; only the places of the other candidates are sorted anew, Hauptartikel targets among them with
    ``weight``. Idea 2: at most ``cap`` targets per topic get it, the strongest by their own score."""

    def rank(main: Any, candidates: list[str]) -> list[str]:
        shipped = related.rank_related_candidates(main, candidates)
        stems = related.title_stems(main.title)
        content_lower = chr(10).join(p.text for s in main.sections for p in s.paragraphs).lower()
        headings = {h.lower() for s in main.sections for h in s.path}
        targets = hauptartikel_targets(main.title)

        def base_score(link: str) -> float:  # the shipped score of a candidate without a stem in its title
            key = link.lower()
            score = 0.0
            if any(key == h or key in h or h in key for h in headings):
                score += related.NAMES_A_HEADING
            if len(link) >= 3:
                score += min(content_lower.count(key), related.MAX_MENTIONS) * related.PER_MENTION
            if 4 <= len(link) <= 40:
                score += related.ORDINARY_LENGTH
            return score

        has_stem = [any(stem in link.lower() for stem in stems) for link in shipped]
        others = [link for link, stem in zip(shipped, has_stem) if not stem]
        boosted = [link for link in others if link.lower() in targets]
        if cap is not None:
            boosted = sorted(boosted, key=lambda link: (-base_score(link), others.index(link)))[:cap]
        lucky = set(boosted)
        order = {link: i for i, link in enumerate(others)}
        others = sorted(others, key=lambda link: (-(base_score(link) + (weight if link in lucky else 0.0)), order[link]))
        refill = iter(others)
        return [link if stem else next(refill) for link, stem in zip(shipped, has_stem)]

    return rank



def printed(topic: str) -> dict[str, list[tuple[str, str]]]:
    prepared = service.prepare(request(topic))
    titles = {src.source_id: src.title for src in prepared.sources} if hasattr(prepared.sources[0], "source_id") else {}
    matched = service.match(prepared, STRATEGY, TARGET_LENGTH).assignment
    slots = {slot.id: slot.title for slot in prepared.template.content_slots()}
    out = {}
    for slot, items in matched.assigned.items():
        rows = []
        for item in items:
            chunk = item.chunk
            source = titles.get(chunk.source_id, chunk.source_id)
            rows.append((source, " ".join(chunk.text.split())))
        out[slots.get(slot, slot)] = rows
    return out, [src.title for src in prepared.sources]


shipped_rank = corpus_sources.rank_related_candidates
for topic in sys.argv[3:]:
    before, corpus_before = printed(topic)
    corpus_sources.rank_related_candidates = guarded_ranking(24.0, 3)
    try:
        after, corpus_after = printed(topic)
    finally:
        corpus_sources.rank_related_candidates = shipped_rank
    print("=" * 100)
    print(f"THEMA: {topic}")
    print("Korpus heute :", corpus_before)
    print("Korpus neu   :", corpus_after)
    for slot in list(dict.fromkeys(list(before) + list(after))):
        b, a = before.get(slot, []), after.get(slot, [])
        gone = [r for r in b if r not in a]; new = [r for r in a if r not in b]
        if not gone and not new:
            continue
        print(f"-- Baustein: {slot}")
        for src, text in gone:
            print(f"   - entfällt [{src}]: {text[:230]}")
        for src, text in new:
            print(f"   + neu      [{src}]: {text[:230]}")
