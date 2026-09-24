"""A compendium from the metadata of a material against one from a term (M23), in the flow of the service.

M21 measured how the service finds the main article of a real WLO material; this goes on to the compendium itself.
For every material of the gold eval/materialwahl/materialien.yaml (40 materials of the WLO production, read anew and
anonymously from their repository) it builds part 1 and part 2 in six ways:

- B    the term a teacher would type (`begriff` of the gold), without the node
- K0   the node alone, as node input works today (its title as the topic, D45), preset llm-free
- K0b  the node alone with the preset balanced: the LLM decides an unsure article (D35)
- KL   the node, and the LLM names the topic from title, subjects, keywords and description (M21 S4)
- KEl  the entities of title and description (the dictionary of /entities, ranked as M21 S3), up to ten articles
- KEa  the entities the old service's linker names for title, description and keywords (its prompt word for word,
       alter_linker.py), up to ten articles

The two entity ways exist only here, as a stand-in for a method like the old service's: the service builds its corpus
from one article, so for them the corpus step is replaced by the articles of the entities - the first one as main
article, disambiguation pages left out - and everything after it (segmenting, matching, writing, part 2) runs in the
service. Part 1 is written without the LLM in all six ways; the LLM decides the article in K0b and names the topic
in KL or the entities in KEa.

Per compendium it records whether it was made, its main article and whether the gold accepts it, how many paragraphs
each source article printed (the chunk ids of the blocks, as in M10), filled blocks, length, part 2 elements,
seconds and tokens: titles and numbers only. Descriptions and article leads go into the judging sheet <sheet.json>,
which belongs outside the repository; its notes (eval/materialwahl/kompendium_noten.yaml) are what
mc_material_kompendium_auswertung.py turns into shares of fitting paragraphs.

Usage (project venv, from the project root; needs LLM_ENABLED and B_API_KEY in .env, the key is never printed):
python docs/entwicklung/messung/mc_material_kompendium.py <out.json> <sheet.json>
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

os.environ["LLM_ENABLED"] = "true"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from alter_linker import MAX_ENTITIES, labels_of, user_prompt, variations
from alter_linker import SYSTEM as LINKER_SYSTEM
from materialwege import PROMPT_CHARS, ask_llm, canonical, entity_ranking

from app.cli_common import cli_service
from app.domain.models import Compendium
from app.domain.requests import GenerateRequest
from app.llm.client import BApiClient, LlmError
from app.service import TopicNotFoundError
from app.settings import get_settings
from app.sources.wlo.client import EduSharingClient, EduSharingError

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD = Path("eval") / "materialwahl" / "materialien.yaml"
PARTS: list[Any] = ["world", "curricula"]
SEED = 23  # shuffles the articles of a material on the sheet, so their order says nothing about the way


def entity_corpus(service: Any, titles: list[str]) -> Callable[..., list[Any]]:
    """build_corpus for the entity ways: the articles of the entities, the resolved first one as main article."""
    wiki = service.registry.primary_archive

    def build(resolution: Any, slots: Any, max_articles: int) -> list[Any]:
        sources: list[Any] = []
        seen: set[str] = set()
        for title in [resolution.title, *titles]:
            article = wiki.read(title)
            if article is None or wiki.parse(article).is_disambiguation or article.title.lower() in seen:
                continue
            seen.add(article.title.lower())
            source = wiki.to_source(article, is_primary=not sources)
            # "entity" keeps every paragraph: the linked and search filter would keep only those naming the first one
            source.origin = "primary" if not sources else "entity"
            sources.append(source)
            if len(sources) == max_articles:
                break
        return sources

    return build


def looked_up(wiki: Any, labels: list[str]) -> list[str]:
    """The articles behind the linker's labels: directly with redirects, then the old spelling variants."""
    titles: list[str] = []
    for label in labels:
        for candidate in [label, *variations(label)]:
            article = wiki.read(candidate)
            if article is not None:
                if not wiki.parse(article).is_disambiguation and article.title not in titles:
                    titles.append(article.title)
                break
    return titles


def ask_linker(client: BApiClient, info: Any) -> tuple[list[str], int]:
    text = f"{info.title}\n{info.description[:PROMPT_CHARS]}\nSchlagwörter: {', '.join(info.keywords) or 'keine'}"
    result = client.chat(
        [{"role": "system", "content": LINKER_SYSTEM}, {"role": "user", "content": user_prompt(text)}],
        max_output_tokens=client.completion_limit(800),  # the old max_tokens
    )
    try:
        labels = labels_of(result.text)[:MAX_ENTITIES]
    except (ValueError, AttributeError):
        labels = []
    return labels, result.total_tokens


def generate(service: Any, request: GenerateRequest, corpus: Callable[..., list[Any]] | None = None) -> Any:
    """The compendium, or the reason there is none; ``corpus`` stands in for the corpus step of the entity ways."""
    original = service.registry.build_corpus
    if corpus is not None:
        service.registry.build_corpus = corpus
    started = time.perf_counter()
    try:
        return service.generate(request), round(time.perf_counter() - started, 2)
    except TopicNotFoundError:
        return "kein Artikel", round(time.perf_counter() - started, 2)
    finally:
        service.registry.build_corpus = original


def summary(result: Compendium, accepted: set[str]) -> dict[str, Any]:
    by_id = {source.source_id: source for source in result.sources}
    printed: Counter[tuple[str, str]] = Counter()
    for section in result.sections:
        for chunk_id in section.chunk_ids:
            source = by_id[chunk_id.rsplit(":c", 1)[0]]
            printed[(source.project, source.title)] += 1
    curricula = result.curricula
    return {
        "hauptartikel": result.resolution.title,
        "richtig": result.resolution.title in accepted,
        "gedruckt": [{"projekt": p, "titel": t, "absaetze": n} for (p, t), n in printed.most_common()],
        "bausteine": result.audit.sections_filled,
        "zeichen": len(result.markdown),
        "teil2": (curricula.summary.get("matches", 0) if curricula and curricula.available else None),
        "tokens_dienst": (result.audit.llm_tokens or {}).get("total", 0),
    }


def run_material(service: Any, llm: BApiClient, entry: dict[str, Any], leads: dict[str, str]) -> dict[str, Any]:
    wiki = service.registry.primary_archive
    accepted = canonical(wiki, entry["akzeptiert"])
    node = {"node_id": entry["node_id"], "repository": entry["repository"]}
    info = EduSharingClient(entry["repository"], timeout_s=30).node(entry["node_id"])
    service.read_node(entry["node_id"], entry["repository"])  # the service's cache holds the node before timing
    ways: dict[str, dict[str, Any]] = {}

    def record(way: str, request: GenerateRequest | None, extra: dict[str, Any], corpus: Any = None) -> None:
        if request is None:
            ways[way] = {"status": extra.pop("status"), **extra}
            return
        result, seconds = generate(service, request, corpus)
        if isinstance(result, str):
            ways[way] = {"status": result, "sekunden": seconds, **extra}
            return
        for source in result.sources:
            leads.setdefault(source.title, source.lead)
        ways[way] = {"status": "ok", "sekunden": seconds, **summary(result, accepted), **extra}

    def by_entities(way: str, entities: list[str], found: dict[str, Any]) -> None:
        if not entities:
            record(way, None, {"status": "keine Entitäten", **found})
            return
        request = GenerateRequest(**node, topic=entities[0], **llm_free)
        record(way, request, found, entity_corpus(service, entities))

    llm_free = {"parts": PARTS, "preset": "llm-free"}
    term = entry.get("begriff")
    record("B", GenerateRequest(topic=term, **llm_free) if term else None, {} if term else {"status": "kein Begriff"})
    record("K0", GenerateRequest(**node, **llm_free), {})
    record("K0b", GenerateRequest(**node, parts=PARTS, preset="balanced"), {})

    started = time.perf_counter()
    try:
        named, tokens = ask_llm(llm, info)
    except LlmError as exc:  # counted as no topic named, like a failed linker below
        named, tokens = "", 0
        print(f"   LLM-Fehler: {str(exc)[:120]}")
    asked = {"genannt": named, "tokens_frage": tokens, "sekunden_frage": round(time.perf_counter() - started, 2)}
    request = GenerateRequest(**node, topic=named, **llm_free) if named else None
    record("KL", request, asked if named else {"status": "kein Thema genannt", **asked})

    started = time.perf_counter()
    ranking = [title for title, _ in entity_ranking(service, info.title, info.description, list(info.keywords))]
    entities = ranking[:MAX_ENTITIES]
    by_entities("KEl", entities, {"entitaeten": entities, "sekunden_frage": round(time.perf_counter() - started, 2)})

    started = time.perf_counter()
    try:
        labels, tokens = ask_linker(llm, info)
    except LlmError as exc:
        labels, tokens = [], 0
        print(f"   Linker-Fehler: {str(exc)[:120]}")
    entities = looked_up(wiki, labels)
    seconds = round(time.perf_counter() - started, 2)
    by_entities(
        "KEa", entities, {"labels": labels, "entitaeten": entities, "tokens_frage": tokens, "sekunden_frage": seconds}
    )

    return {
        "node_id": entry["node_id"],
        "titel": entry["titel"],
        "art": entry["art"],
        "begriff": term,
        "akzeptiert": sorted(accepted),
        "wege": ways,
        "_info": info,  # for the sheet only, dropped before writing
    }


def sheet_rows(material: dict[str, Any], leads: dict[str, str], rng: random.Random) -> list[dict[str, Any]]:
    """Every article that printed a paragraph for this material, once, in an order that hides the ways."""
    titles = sorted(
        {row["titel"] for way in material["wege"].values() if way["status"] == "ok" for row in way["gedruckt"]}
    )
    rng.shuffle(titles)
    info = material["_info"]
    return [
        {
            "node_id": material["node_id"],
            "material": info.title,
            "faecher": list(info.subject_labels),
            "schlagwoerter": list(info.keywords)[:12],
            "beschreibung": info.description[:700],
            "artikel": title,
            "anfang": (leads.get(title) or "")[:300],
        }
        for title in titles
    ]


def main() -> None:
    out_path, sheet_path = Path(sys.argv[1]), Path(sys.argv[2])
    if out_path.exists():
        raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
    settings = get_settings()
    service = cli_service(ZIMS)
    llm = BApiClient(
        settings.b_api_url,
        settings.b_api_key,
        provider=settings.b_api_provider,
        model=settings.b_api_model,
        max_concurrency=1,
    )
    gold = yaml.safe_load(GOLD.read_text(encoding="utf-8"))["materialien"]
    rng = random.Random(SEED)
    materials, sheet, leads = [], [], {}
    for entry in gold:
        try:
            material = run_material(service, llm, entry, leads)
        except EduSharingError as exc:  # a material gone since M21 is reported, not measured
            print(f"{entry['node_id'][:8]} nicht lesbar: {str(exc)[:100]}")
            continue
        sheet.extend(sheet_rows(material, leads, rng))
        del material["_info"]
        materials.append(material)
        states = " ".join(
            f"{way}:{'+' if row.get('richtig') else ('-' if row['status'] == 'ok' else 'x')}"
            for way, row in material["wege"].items()
        )
        print(f"{entry['art']:8} {entry['titel'][:40]:40} {states}")
    out_path.write_text(json.dumps(materials, ensure_ascii=False, indent=1), encoding="utf-8")
    sheet_path.write_text(json.dumps(sheet, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(materials)} Materialien, {len(sheet)} Artikel zum Beurteilen in {sheet_path}")


main()
