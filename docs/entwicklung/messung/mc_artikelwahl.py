"""Article selection (project venv): topic resolution against eval/artikelwahl/hauptartikel.yaml, and the corpus of
every normal topic with what each article contributes.

Every query runs through CompendiumService.prepare, the service's own path: normalisation, resolution, corpus and
segmentation with the archives of the server (Wikipedia and Klexikon). A resolution is correct when its title is one
of the expected titles or the target of a redirect Wikipedia sets for one of them. For the normal topics the corpus
is recorded twice: the articles build_corpus picks, and those that keep paragraphs after the topic-stem filter,
with their paragraph count and the paragraphs the standard strategy (hybrid_light with Model2Vec, 12,000 characters)
prints. The old service's articles for the ten gold topics come from its raw runs (M2, best case): the article
behind the URL it fetched, which differs from the title its LLM guessed where Wikipedia redirected.

Two files are written: the result without any article text (for the repository) and a pool for the relevance
labels with the opening of every article, which stays outside the repository.

Usage: python mc_artikelwahl.py <old_runs_dir> <out.json> <pool.json>
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import yaml

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.service import TopicNotFoundError  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\artikelwahl\hauptartikel.yaml")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 12_000
LEAD_CHARS = 300
GOLD_TOPICS = {
    "Barockliteratur", "Bruchrechnung", "Demokratie", "Französische Revolution", "Klimawandel", "Optik",
    "Photosynthese", "Programmiersprache", "Säure-Base-Konzepte", "Sinfonie",
}

old_runs, out_path, pool_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
service = cli_service(ZIMS)
service.settings.model2vec_path = M2V
wiki = service.registry.primary_archive
queries = yaml.safe_load(GOLD.read_text(encoding="utf-8"))["anfragen"]


def accepted(titles: list[str]) -> list[str]:
    """The expected titles and the redirect targets Wikipedia sets for them."""
    found = list(titles)
    for title in titles:
        # read_article: a gold title may be a redirect to a section ("Elektrischer Leiter" -> Leiter (Physik)), M35
        article = wiki.read_article(title) if wiki is not None else None
        if article is not None and article.title not in found:
            found.append(article.title)
    return found


def opening(text: str) -> str:
    return " ".join(text.split())[:LEAD_CHARS]


results: list[dict] = []
corpora: dict[str, dict] = {}
pool: dict[str, dict[str, str]] = {}
service.match(service.prepare(GenerateRequest(topic="Magnetismus", parts=["world"])), "hybrid_light", TARGET_LENGTH)
for entry in queries:
    query, kind = entry["anfrage"], entry["art"]
    ok_titles = accepted(entry["erwartet"])
    started = time.perf_counter()
    try:
        prepared = service.prepare(GenerateRequest(topic=query, parts=["world"]))
    except TopicNotFoundError as exc:
        results.append({"anfrage": query, "art": kind, "akzeptiert": ok_titles, "titel": None, "richtig": False,
                        "begriffsklaerung": exc.resolution.disambiguation, "kontext": exc.resolution.context})
        print(f"{query:40s} NICHT GEFUNDEN")
        continue
    seconds = time.perf_counter() - started
    resolution = prepared.resolution
    correct = resolution.title in ok_titles
    results.append({
        "anfrage": query, "art": kind, "akzeptiert": ok_titles, "titel": resolution.title, "richtig": correct,
        "normalisiert": resolution.normalized, "kontext": resolution.context,
        "begriffsklaerung": resolution.disambiguation, "alternativen": resolution.alternatives,
        "sekunden": round(seconds, 2), "schritte_ms": dict(prepared.timings),
    })
    print(f"{query:40s} {'richtig' if correct else 'FALSCH '}  {resolution.title}")
    if kind != "normal":
        continue

    picked = service.registry.build_corpus(
        resolution, slots=prepared.template.content_slots(), max_articles=service.settings.corpus_max_articles
    )
    matched = service.match(prepared, "hybrid_light", TARGET_LENGTH)
    chunks_per_source = Counter(chunk.source_id for chunk in prepared.chunks)
    printed = Counter(item.chunk.source_id for items in matched.assignment.assigned.values() for item in items)
    kept = {source.source_id for source in prepared.sources}
    corpora[query] = {
        "hauptartikel": resolution.title,
        "artikel": [
            {
                "titel": source.title, "projekt": source.project, "herkunft": source.origin,
                "im_korpus": source.source_id in kept, "absaetze": chunks_per_source.get(source.source_id, 0),
                "gedruckt": printed.get(source.source_id, 0),
            }
            for source in picked
        ],
        "absaetze_gesamt": len(prepared.chunks), "gekappt": prepared.chunks_truncated,
    }
    for source in picked:
        pool.setdefault(query, {})[f"{source.project}:{source.title}"] = opening(source.lead_text)

old: dict[str, list[dict]] = {}
for path in sorted(old_runs.glob("*.json")):
    run = json.loads(path.read_text(encoding="utf-8"))
    if run["topic"] not in GOLD_TOPICS:
        continue
    articles: dict[str, dict] = {}
    for entity in run["result"]["linker_output"]["entities"]:
        wikipedia = entity.get("sources", {}).get("wikipedia", {})
        url = wikipedia.get("url_de") or ""
        if wikipedia.get("status") not in {"found", "found_from_prompt"} or "/wiki/" not in url:
            continue
        title = unquote(url.rsplit("/wiki/", 1)[1]).split("#")[0].replace("_", " ")
        article = articles.setdefault(title, {"titel": title, "begriffe": []})
        article["begriffe"].append(entity.get("entity"))
        pool.setdefault(run["topic"], {}).setdefault(f"wikipedia:{title}", opening(wikipedia.get("extract", "")))
    old[run["topic"]] = list(articles.values())

by_kind: dict[str, list[bool]] = {}
for result in results:
    by_kind.setdefault(result["art"], []).append(result["richtig"])
summary = {kind: f"{sum(flags)} von {len(flags)}" for kind, flags in by_kind.items()}
out_path.write_text(json.dumps({"anfragen": results, "korpus": corpora, "alter_dienst": old, "zusammenfassung": summary},
                               ensure_ascii=False, indent=1), encoding="utf-8")
pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
print("\nHauptartikel richtig:", summary)
print("Artikel im Pool:", sum(len(v) for v in pool.values()))
