"""M38: set-like topics without a large LLM - can the archive, spaCy's parse or a small fast model do what N does?

Jan, 2026-09-26: llm-free stays without an LLM, but could spaCy or another way without one find more fitting articles
for a topic like "deutsche Dichter"? And could a small fast model close the gap, in at most 2 to 3 s? The question N of
M37 (an LLM names the overview article and up to eight parts) is to come into balanced and the profiles above it;
first check whether that needs a large LLM. Ways, each through part 1 of the service with the text verbatim:

- R: llm-free as it is, as in M37 - a check that this run reproduces M37, so M37's grades apply;
- P: without an LLM. spaCy parses the topic: head noun (Planeten -> Planet) and what qualifies it (des
  Sonnensystems, der Romantik, deutsche). The overview is the rules' article when they are sure and it is no list,
  else the first full-text hit whose title carries a qualifying word, else the qualifying word's own article. The parts
  are the overview's links, in their order, whose first paragraph names the head noun - read without parsing the
  article, at most 60 - and for a list page the list's links too; for a topic that joins two things ("Klimawandel und
  Landwirtschaft") the links both halves share. Only where the rules are unsure, land on a list, the head noun is
  plural or two things are joined; otherwise P is R;
- L8 and Q30: the question N word for word, asked a small fast model of the b-api (academiccloud:
  meta-llama-3.1-8b-instruct, qwen3-30b-a3b-instruct-2507); the named titles are looked up as in M37.

It runs in the development container, which has the spaCy model and the archives, with MODEL2VEC_PATH empty: M37 ran
without Model2Vec, and the matching has to be the same for its grades to hold. Every article a way printed that M37 did
not grade is graded blind as in M37 (eval/sammelthemen/). Leads go to the sheet only.

Usage (in the container, with this file, alter_linker.py, mc_sammelthemen.py and eval/artikelwahl/korpus_labels.yaml
in one directory on PYTHONPATH):
python mc_sammelthemen_ohne_llm.py <dir> <out.json> <sheet.json> [--normal]
"""

from __future__ import annotations

import ast
import html
import json
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ["MODEL2VEC_PATH"] = ""  # the matching of M37, so its grades apply
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import yaml  # noqa: E402
from alter_linker import variations  # noqa: E402

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import Compendium  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.knowledge.article_choice import read_object  # noqa: E402
from app.knowledge.recognise import load_spacy  # noqa: E402
from app.llm.client import BApiClient, LlmError  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SMALL_MODELS = {"L8": "meta-llama-3.1-8b-instruct", "Q30": "qwen3-30b-a3b-instruct-2507"}
MAX_PARTS = 8
MAX_READS = 60  # candidate links P reads the first paragraph of
QUALIFIERS = {"ag", "nk", "mnr", "pg", "cj", "app"}  # spaCy dependencies of the words that qualify the head noun
ACTOR = re.compile(r"^- \*\*\[([^\]]+)\]", re.MULTILINE)
FIRST_PARAGRAPH = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL)
TAG = re.compile(r"<[^>]+>")

directory, out_path, sheet_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
NORMAL = "--normal" in sys.argv
m37 = ast.parse((directory / "mc_sammelthemen.py").read_text(encoding="utf-8"))
WANTED = ("TOPICS", "NEW_SYSTEM", "NEW_QUESTION", "MAX_NAMED")
M37 = {
    n.targets[0].id: ast.literal_eval(n.value)
    for n in m37.body
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in WANTED
}
TOPICS: list[str] = M37["TOPICS"]
if NORMAL:
    TOPICS = list(yaml.safe_load((directory / "korpus_labels.yaml").read_text(encoding="utf-8"))["labels"])

service = cli_service(None)
wiki = service.registry.primary_archive
assert wiki is not None
nlp = load_spacy("de_core_news_md")
assert nlp is not None, "the spaCy model of the image is missing"
settings = service.settings
base_url = settings.b_api_base_url or "https://b-api.staging.openeduhub.net"
small = {
    way: BApiClient(base_url, settings.b_api_key, provider="academiccloud", model=model, timeout_s=60)
    for way, model in SMALL_MODELS.items()
}


def first_paragraph(title: str) -> str:
    """The first paragraph of an article, read from its HTML without parsing the whole page (P reads many)."""
    article = wiki.read(title)
    if article is None:
        return ""
    for found in FIRST_PARAGRAPH.finditer(article.html[:30_000]):
        text = " ".join(html.unescape(TAG.sub("", found.group(1))).split())
        if len(text) > 40:
            return text[:300]
    return ""


def stem(token: Any) -> str:
    """The head noun as it stands in a lead: the lemma of a noun, else the word without a plural ending."""
    if token.pos_ in ("NOUN", "PROPN"):
        return str(token.lemma_)
    word = str(token.text)
    for ending in ("en", "e", "n"):
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)]
    return word


def links_of(title: str) -> list[str]:
    article = wiki.read_article(title)
    return list(dict.fromkeys(wiki.parse(article).links)) if article is not None else []


def usable(title: str) -> bool:
    return not title.startswith("Liste ") and "(Begriffsklärung)" not in title


def without_llm(topic: str) -> dict[str, Any]:
    """P: the overview and the parts, and why; ``titles`` empty where P leaves the topic to the rules."""
    started = time.perf_counter()
    doc = nlp(topic)
    root = next((t for t in doc if t.dep_ == "ROOT"), doc[0])
    nouns = [t for t in doc if t.pos_ in ("NOUN", "PROPN") and t.i != root.i]
    qualifiers = [t for t in doc if t.i != root.i and t.dep_ in QUALIFIERS and t.pos_ in ("NOUN", "PROPN", "ADJ")]
    plural = "Plur" in root.morph.get("Number")
    joined = not plural and bool(nouns) and any(t.pos_ in ("CCONJ", "ADP") for t in doc)
    rules = service.registry.resolve_topic(topic)
    listed = bool(rules.title) and rules.title.startswith("Liste ")
    info: dict[str, Any] = {"regeln": rules.title, "regeln_methode": rules.method, "mehrzahl": plural,
                            "verbindung": joined, "kopf": stem(root)}  # fmt: skip
    if rules.confident and not listed and not plural and not joined:
        return {**info, "titles": [], "grund": "Regeln sicher, kein Sammelthema", "sekunden": 0.0}
    titles: list[str] = []
    if joined:
        halves = [rules.title if rules.confident and rules.title else root.lemma_, nouns[0].lemma_]
        found = [service.registry.resolve_topic(half).title for half in halves]
        if all(found):
            second = set(links_of(str(found[1])))
            shared = [t for t in links_of(str(found[0])) if t in second and t not in found and usable(t)]
            titles = [str(found[0]), *shared[:MAX_PARTS]]
        grund = "Verbindung: gemeinsame Links beider Hälften"
    else:
        head = stem(root).lower()
        if rules.confident and rules.title and not listed:
            candidates = [str(rules.title)]
        else:
            candidates = []
            if qualifiers:
                own = service.registry.resolve_topic(str(qualifiers[-1].lemma_)).title
                candidates += [own] if own else []
            words = " ".join([stem(root), *(str(t.lemma_) for t in qualifiers)])
            hits = [hit for hit in wiki.search(words, limit=10) if usable(hit) and "(" not in hit]
            candidates += [hit for hit in hits if hit not in candidates][:2]
            if listed:
                candidates.append(str(rules.title))
        yields = {candidate: members(candidate, head) for candidate in dict.fromkeys(candidates)}
        info["kandidaten"] = {candidate: len(found) for candidate, found in yields.items()}
        hub = max(yields, key=lambda c: (len(yields[c]), not c.startswith("Liste "))) if yields else None
        overview = hub
        if hub is not None and hub.startswith("Liste "):
            others = [c for c in yields if not c.startswith("Liste ") and len(yields[c]) >= 2]
            overview = max(others, key=lambda c: len(yields[c])) if others else hub
        titles = [overview, *yields[hub][:MAX_PARTS]] if hub is not None and overview is not None else []
        grund = "Gruppe: der Knoten mit den meisten verlinkten Vertretern"
    return {**info, "titles": titles, "grund": grund, "sekunden": round(time.perf_counter() - started, 2)}


def members(hub: str, head: str) -> list[str]:
    """The hub's links, in their order, whose first paragraph names the head noun; the first MAX_READS looked at."""
    found: list[str] = []
    for title in links_of(hub)[:MAX_READS]:
        if title != hub and usable(title) and head in first_paragraph(title).lower()[:200]:
            found.append(title)
    return found


def looked_up(labels: list[str]) -> list[str]:
    """The articles behind the labels, as M37: directly with redirects, then the old spelling variants."""
    titles: list[str] = []
    for label in labels:
        for candidate in [label, *variations(label)]:
            article = wiki.read_article(candidate)
            if article is not None:
                if not wiki.parse(article).is_disambiguation and article.title not in titles:
                    titles.append(article.title)
                break
    return titles


def entity_corpus(titles: list[str]) -> Callable[..., list[Any]]:
    """build_corpus for the named articles, the first one as main article, every paragraph kept (M23, M37)."""

    def build(resolution: Any, slots: Any, max_articles: int, material: str | None = None) -> list[Any]:
        sources: list[Any] = []
        seen: set[str] = set()
        for title in [resolution.title, *titles]:
            article = wiki.read_article(title)
            if article is None or wiki.parse(article).is_disambiguation or article.title.lower() in seen:
                continue
            seen.add(article.title.lower())
            source = wiki.to_source(article, is_primary=not sources)
            source.origin = "primary" if not sources else "entity"
            sources.append(source)
            if len(sources) == max_articles:
                break
        return sources

    return build


def generate(request: GenerateRequest, corpus: Callable[..., list[Any]] | None = None) -> tuple[Compendium, float]:
    original = service.registry.build_corpus
    if corpus is not None:
        service.registry.build_corpus = corpus  # type: ignore[method-assign]
    started = time.perf_counter()
    try:
        return service.generate(request), round(time.perf_counter() - started, 2)
    finally:
        service.registry.build_corpus = original  # type: ignore[method-assign]


def summary(result: Compendium, sheet: dict[str, str]) -> dict[str, Any]:
    """What a way printed, per article, and who its actors are, as M37; the leads go to the sheet only."""
    by_id = {source.source_id: source for source in result.sources}
    printed: Counter[str] = Counter()
    for section in result.sections:
        for chunk_id in section.chunk_ids:
            source = by_id[chunk_id.rsplit(":c", 1)[0]]
            printed[source.title] += 1
            sheet.setdefault(source.title, source.lead[:400])
    actors = next((s.text for s in result.sections if s.slot_key == "akteure"), "")
    persons = ACTOR.findall(actors.split("#### Person", 1)[1].split("#### ", 1)[0]) if "#### Person" in actors else []
    return {
        "hauptartikel": result.resolution.title,
        "methode": result.resolution.method,
        "sicher": result.resolution.confident,
        "gedruckt": [{"titel": t, "absaetze": n} for t, n in printed.most_common()],
        "bausteine": result.audit.sections_filled,
        "personen": persons,
    }


def from_titles(titles: list[str], sheet: dict[str, str]) -> dict[str, Any]:
    request = GenerateRequest(topic=titles[0], parts=["world"], preset="llm-free")  # type: ignore[arg-type]
    result, seconds = generate(request, entity_corpus(titles))
    return {"sekunden": seconds, **summary(result, sheet)}


def ask_small(client: BApiClient, topic: str) -> dict[str, Any]:
    question = M37["NEW_QUESTION"].format(topic=topic, count=M37["MAX_NAMED"])
    started = time.perf_counter()
    try:
        answer = client.chat(
            [{"role": "system", "content": M37["NEW_SYSTEM"]}, {"role": "user", "content": question}],
            max_output_tokens=client.completion_limit(600),
        )
        data, tokens = read_object(answer.text) or {}, answer.total_tokens
    except LlmError as exc:
        data, tokens = {}, 0
        print(f"   {client.model}: {str(exc)[:120]}")
    seconds = round(time.perf_counter() - started, 2)
    overview = str(data.get("uebersicht") or "").strip()
    named = [str(t).strip() for t in data.get("artikel") or [] if str(t).strip()][: M37["MAX_NAMED"]]
    return {"uebersicht": overview, "genannt": named, "gefunden": looked_up([overview, *named] if overview else named),
            "tokens_frage": tokens, "sekunden_frage": seconds}  # fmt: skip


rows: list[dict[str, Any]] = []
sheets: dict[str, dict[str, str]] = {}
for topic in TOPICS:
    sheet = sheets.setdefault(topic, {})
    ways: dict[str, Any] = {}
    rules_result, seconds = generate(GenerateRequest(topic=topic, parts=["world"], preset="llm-free"))  # type: ignore[arg-type]
    ways["R"] = {"sekunden": seconds, **summary(rules_result, sheet)}

    found = without_llm(topic)
    titles = found.pop("titles")
    ways["P"] = {**(from_titles(titles, sheet) if titles else ways["R"]), "verfahren": found, "titel": titles}

    for way, client in small.items():
        asked = ask_small(client, topic)
        ways[way] = {**(from_titles(asked["gefunden"], sheet) if asked["gefunden"] else {"status": "keine Artikel"}),
                     **asked}  # fmt: skip

    rows.append({"thema": topic, "wege": ways})
    marks = "  ".join(f"{w}: {ways[w].get('hauptartikel', ways[w].get('status'))}" for w in ("R", "P", *small))
    print(f"{topic:36s} P {found['sekunden']:4.2f} s  {marks}", flush=True)

out_path.write_text(json.dumps({"themen": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
sheet_path.write_text(json.dumps(sheets, ensure_ascii=False, indent=1), encoding="utf-8")
