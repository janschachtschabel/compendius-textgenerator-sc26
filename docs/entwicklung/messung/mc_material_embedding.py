"""Whether static embeddings find the article of a real material without an LLM (M24): a pilot over the whole archive.

For the 40 materials of eval/materialwahl/materialien.yaml (read anew and anonymously from their repository) it asks
the service's Model2Vec model for the closest Wikipedia articles, with three queries: the material as the LLM of M21
and M23 reads it (title, subjects, keywords, description up to 1,500 characters), the material without its
description, and the term of M23 as a check of the method itself. Stage 1 embeds the title of every entry of the
archive, a redirect standing for its target, block by block, and keeps the closest articles per query; nothing is
written to disk, so for these queries the pass gives what a full index would, without building one. Stage 2 embeds
title and lead of the 200 closest and ranks them again, disambiguation pages left out. A third way ranks the ten
local entities M23 recognised (KEl) the same way. Last, it scores every article M23 printed and judged
(eval/materialwahl/kompendium_noten.yaml) by the same similarity to its material, and records whether it and the
main article KL chose in M23 link to one another: two signals that could filter side articles or the entities of the
old service without an LLM.

Per material and way it keeps the first 20 articles with their similarity: titles and numbers only. The timings of
both stages and of a search over the vectors are what the storage and speed of a real index are estimated from;
mc_material_embedding_auswertung.py evaluates the run.

Usage (project venv, from the project root; <model> is the service's model directory, /models/m2v in the image):
python docs/entwicklung/messung/mc_material_embedding.py <model> <out.json> [<entries, for a probe run>]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from materialwege import PROMPT_CHARS, canonical
from model2vec import StaticModel

from app.sources.wlo.client import EduSharingClient, EduSharingError
from app.sources.zim.archive import ZimArchive

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

WIKIPEDIA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data\wikipedia_de_all_nopic_2026-01.zim")
GOLD = Path("eval") / "materialwahl" / "materialien.yaml"
M23 = Path("docs") / "entwicklung" / "messung" / "ergebnisse" / "m23_material_kompendium.json"
NOTES = Path("eval") / "materialwahl" / "kompendium_noten.yaml"  # the second rater's file names the same articles
BLOCK = 50_000  # entries embedded at once
KEEP = 600  # raw hits kept per query in stage 1, so that 200 remain once redirects fold into their targets
CANDIDATES = 200  # articles per query that stage 2 reads
LEAD_CHARS = 600
SAVED = 20


def queries(info: Any, term: str | None) -> dict[str, str]:
    subjects, keywords = ", ".join(info.subject_labels) or "keine", ", ".join(info.keywords) or "keine"
    short = f"Titel: {info.title}\nFächer: {subjects}\nSchlagwörter: {keywords}"
    found = {"voll": f"{short}\nBeschreibung: {info.description[:PROMPT_CHARS]}", "kurz": short}
    if term:
        found["begriff"] = term
    return found


def unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)


def stream(model: StaticModel, targets: np.ndarray, limit: int | None) -> tuple[list[list[tuple[float, str]]], dict]:
    """Stage 1: every title of the archive against every query, keeping the KEEP closest per query."""
    archive = WIKIPEDIA_ARCHIVE._archive
    best: list[list[tuple[float, str]]] = [[] for _ in range(len(targets))]
    texts: list[str] = []
    aims: list[str] = []
    seconds = {"lesen": 0.0, "einbetten": 0.0, "vergleichen": 0.0}
    counts = {"eintraege": 0, "artikel": 0, "weiterleitungen": 0}

    def flush() -> None:
        started = time.perf_counter()
        vectors = unit(model.encode(texts, use_multiprocessing=False))
        seconds["einbetten"] += time.perf_counter() - started
        started = time.perf_counter()
        scores = targets @ vectors.T
        top = np.argpartition(-scores, min(KEEP, scores.shape[1] - 1), axis=1)[:, :KEEP]
        for q, columns in enumerate(top):
            merged = best[q] + [(float(scores[q, c]), aims[c]) for c in columns]
            best[q] = sorted(merged, reverse=True)[:KEEP]
        seconds["vergleichen"] += time.perf_counter() - started
        texts.clear()
        aims.clear()

    total = archive.entry_count if limit is None else min(limit, archive.entry_count)
    started = time.perf_counter()
    for index in range(total):
        entry = archive._get_entry_by_id(index)
        target, hops = entry, 0
        while target.is_redirect and hops < 3:
            target, hops = target.get_redirect_entry(), hops + 1
        if target.is_redirect:
            continue
        counts["eintraege"] += 1
        counts["weiterleitungen" if entry.is_redirect else "artikel"] += 1
        texts.append(entry.title or entry.path)
        aims.append(target.title or target.path)
        if len(texts) == BLOCK:
            seconds["lesen"] += time.perf_counter() - started
            flush()
            started = time.perf_counter()
            if counts["eintraege"] % 1_000_000 < BLOCK:
                print(f"  {counts['eintraege']:,} Einträge", flush=True)
    seconds["lesen"] += time.perf_counter() - started
    if texts:
        flush()
    return best, {**counts, **{f"sekunden_{k}": round(v, 1) for k, v in seconds.items()}}


def folded(raw: list[tuple[float, str]]) -> list[tuple[str, float]]:
    """The targets of the raw hits, each once with its best similarity, closest first."""
    found: dict[str, float] = {}
    for score, title in raw:
        found[title] = max(score, found.get(title, -1.0))
    return sorted(found.items(), key=lambda item: -item[1])[:CANDIDATES]


def leads(titles: set[str], cache: dict[str, tuple[str, str] | None]) -> None:
    """Per title not read yet the article it names (after a redirect) and its title and lead as one text; None for
    what is no article or a disambiguation page."""
    for title in titles - cache.keys():
        article = WIKIPEDIA_ARCHIVE.read(title)
        if article is None or WIKIPEDIA_ARCHIVE.parse(article).is_disambiguation:
            cache[title] = None
            continue
        lead = WIKIPEDIA_ARCHIVE.to_source(article, is_primary=True).lead_text
        cache[title] = (article.title, f"{article.title}. {lead[:LEAD_CHARS]}")


def ranked(
    target: np.ndarray, titles: list[str], vectors: dict[str, np.ndarray], names: dict[str, str]
) -> list[tuple[str, float]]:
    """The articles behind the titles, closest first, each once: two entities may name the same article."""
    scored = sorted(((float(vectors[t] @ target), names[t]) for t in titles if t in vectors), reverse=True)
    found: dict[str, float] = {}
    for score, name in scored:
        found.setdefault(name, score)
    return list(found.items())


def link_targets(title: str, memo: dict[str, str | None]) -> set[str] | None:
    """The articles an article links to, as the archive names them after a redirect; None without the article."""
    article = WIKIPEDIA_ARCHIVE.read(title)
    if article is None:
        return None
    found = set()
    for link in WIKIPEDIA_ARCHIVE.parse(article).links:
        if link not in memo:
            entry = WIKIPEDIA_ARCHIVE._entry(link)
            for _ in range(3):
                if entry is None or not entry.is_redirect:
                    break
                entry = entry.get_redirect_entry()
            memo[link] = None if entry is None or entry.is_redirect else str(entry.title)
        if memo[link]:
            found.add(memo[link])
    return found


def links(m23: dict[str, Any], titles: list[str], memo: dict[str, str | None]) -> dict[str, Any]:
    """The main article of KL in M23 as anchor, per judged article whether it and the anchor link to one another
    (None without the article), and which ways of M23 printed it."""
    printed: dict[str, set[str]] = {}
    for name, way in m23["wege"].items():
        for row in way.get("gedruckt", []) if way["status"] == "ok" else []:
            printed.setdefault(row["titel"], set()).add(name)
    anchor = m23["wege"]["KL"].get("hauptartikel") if m23["wege"]["KL"]["status"] == "ok" else None
    linked: dict[str, bool | None] = {}
    outgoing = (link_targets(anchor, memo) or set()) if anchor else set()
    for title in titles if anchor else []:
        if title != anchor:
            incoming = link_targets(title, memo)
            linked[title] = None if incoming is None else (title in outgoing or anchor in incoming)
    return {"anker": anchor, "verlinkt": linked, "gedruckt_von": {t: sorted(w) for t, w in printed.items()}}


def search_time(dimensions: int) -> float:
    """Milliseconds for one query against 100,000 vectors, the search a real index would run for each request."""
    vectors = unit(np.random.default_rng(24).standard_normal((100_000, dimensions)).astype(np.float32))
    query = vectors[0]
    started = time.perf_counter()
    for _ in range(20):
        np.argpartition(-(vectors @ query), 200)[:200]
    return round((time.perf_counter() - started) / 20 * 1000, 2)


def saved(hits: list[tuple[str, float]]) -> dict[str, Any]:
    return {"treffer": [[title, round(score, 4)] for title, score in hits[:SAVED]]}


def main() -> None:
    model_path, out_path = sys.argv[1], Path(sys.argv[2])
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    if out_path.exists():
        raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
    gold = yaml.safe_load(GOLD.read_text(encoding="utf-8"))["materialien"]
    m23 = {m["node_id"]: m for m in json.loads(M23.read_text("utf-8"))}
    entities = {node_id: m["wege"]["KEl"].get("entitaeten", []) for node_id, m in m23.items()}
    judged: dict[str, list[str]] = {}
    for note in yaml.safe_load(NOTES.read_text(encoding="utf-8"))["noten"]:
        judged.setdefault(note["node_id"], []).append(note["artikel"])
    model = StaticModel.from_pretrained(model_path)

    materials, texts = [], []
    for entry in gold:
        try:
            info = EduSharingClient(entry["repository"], timeout_s=30).node(entry["node_id"])
        except EduSharingError as exc:  # a material gone since M21 is reported, not measured
            print(f"{entry['node_id'][:8]} nicht lesbar: {str(exc)[:100]}")
            continue
        asked = queries(info, entry.get("begriff"))
        materials.append((entry, list(asked)))
        texts.extend(asked.values())
    targets = unit(model.encode(texts, use_multiprocessing=False))
    print(f"{len(materials)} Materialien, {len(texts)} Anfragen; Stufe 1 über das Archiv", flush=True)

    raw, timing = stream(model, targets, limit)
    hits = [folded(r) for r in raw]

    started = time.perf_counter()
    cache: dict[str, tuple[str, str] | None] = {}
    wanted = {t for found in hits for t, _ in found} | {t for e, _ in materials for t in entities.get(e["node_id"], [])}
    leads(wanted | {t for titles in judged.values() for t in titles}, cache)
    read = round(time.perf_counter() - started, 1)
    readable = {t: pair for t, pair in cache.items() if pair}
    started = time.perf_counter()
    encoded = unit(model.encode([text for _, text in readable.values()], use_multiprocessing=False))
    vectors = dict(zip(readable, encoded, strict=True))
    names = {t: name for t, (name, _) in readable.items()}
    timing.update(
        {
            "stufe2_artikel": len(cache),
            "stufe2_sekunden_lesen": read,
            "stufe2_sekunden_einbetten": round(time.perf_counter() - started, 1),
            "suche_ms_je_100000": search_time(targets.shape[1]),
            "dimensionen": int(targets.shape[1]),
        }
    )

    results, row, memo = [], 0, {}
    linking_started = time.perf_counter()
    for entry, asked in materials:
        found = dict(zip(asked, range(row, row + len(asked)), strict=True))
        row += len(asked)
        ways: dict[str, Any] = {name: {"treffer": []} for name in ("D1", "D1k", "D2", "D2k", "E", "BD1", "BD2")}
        for query, (first, second) in {"voll": ("D1", "D2"), "kurz": ("D1k", "D2k"), "begriff": ("BD1", "BD2")}.items():
            if query in found:
                q = found[query]
                ways[first] = saved(hits[q])
                ways[second] = saved(ranked(targets[q], [t for t, _ in hits[q]], vectors, names))
        ways["E"] = saved(ranked(targets[found["voll"]], entities.get(entry["node_id"], []), vectors, names))
        similar = {
            title: round(float(vectors[title] @ targets[found["voll"]]), 4) if title in vectors else None
            for title in judged.get(entry["node_id"], [])
        }
        results.append(
            {
                "node_id": entry["node_id"],
                "titel": entry["titel"],
                "art": entry["art"],
                "begriff": entry.get("begriff"),
                "akzeptiert": sorted(canonical(WIKIPEDIA_ARCHIVE, entry["akzeptiert"])),
                "wege": ways,
                "aehnlichkeit": similar,
                **links(m23[entry["node_id"]], judged.get(entry["node_id"], []), memo),
            }
        )
    timing["verlinkung_und_rest_sekunden"] = round(time.perf_counter() - linking_started, 1)
    if limit is not None:
        timing["probe_eintraege"] = limit
    out_path.write_text(
        json.dumps({"laufzeit": timing, "materialien": results}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(timing, ensure_ascii=False))


WIKIPEDIA_ARCHIVE = ZimArchive(WIKIPEDIA)
main()
