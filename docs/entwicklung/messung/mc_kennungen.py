"""M41: how right the identifiers of POST /api/v2/entities are per profile - Wikidata, DBpedia, GND - from local data.

No new run: the articles each profile linked for the 40 material texts come from the run through the endpoint after
D62 (m36_entitaeten_dienst.json). For every article the endpoint's own ``identifiers()`` reads GND, Normdaten kind and
VIAF from the ZIM page and the Wikidata number from the local index (``compendium wikidata build``); the DBpedia URI is
built from the title for every article. An identifier is right when its article has grade 2 in M36; recall counts
against the pooled grade-2 articles that carry that identifier. No network. Writes titles, identifiers and counts, no
text.

Usage (inside the development container, where the archives and the index are; PYTHONPATH=/app):
python mc_kennungen.py <out.json> <m36_entitaeten_dienst.json> <m36_entitaeten.json> <noten.yaml> [<noten_zweit.yaml>]
"""

from __future__ import annotations

import collections
import json
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

from app.knowledge.identifiers import Identifiers, identifiers
from app.settings import get_settings
from app.sources.wikidata.index import WikidataIndex
from app.sources.zim.registry import ZimRegistry

PROFILES = ("llm-free", "balanced", "mit Prüfung")  # balanced stands for best-quality too: same way, same articles
CARRIES: dict[str, Callable[[Identifiers | None], bool]] = {
    "Wikipedia/DBpedia": lambda ids: ids is not None,
    "Wikidata": lambda ids: ids is not None and ids.wikidata is not None,
    "GND": lambda ids: ids is not None and ids.gnd is not None,
}

settings = get_settings()
registry = ZimRegistry(settings.zim_path_list) if settings.zim_path_list else ZimRegistry.from_active(settings.zim_dir)
wikipedia = next(archive for archive in registry.archives if archive.id.startswith("wikipedia"))
index = WikidataIndex(settings.wikidata_db_path)
cache: dict[str, Identifiers | None] = {}


def ids_of(title: str) -> Identifiers | None:
    if title not in cache:
        article = wikipedia.read_article(title)
        cache[title] = identifiers(article.title, article.html, index) if article is not None else None
    return cache[title]


def grades_of(path: str) -> dict[tuple[str, str], int]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {(entry["node_id"], entry["artikel"]): int(entry["note"]) for entry in data["noten"]}


def evaluate(service: dict, m36: dict, grades: dict[tuple[str, str], int]) -> dict:
    right_pool = {(node, title) for node in service for title in m36[node]["pool"] if grades.get((node, title)) == 2}
    kinds = collections.Counter(ids.gnd_kind for key in right_pool if (ids := ids_of(key[1])) and ids.gnd)
    result: dict = {
        "pool": {label: sum(1 for key in right_pool if has(ids_of(key[1]))) for label, has in CARRIES.items()},
        "gnd_arten": dict(kinds.most_common()),
        "profile": {},
    }
    for profile in PROFILES:
        links = [(node, title) for node, row in service.items() for title in row["profile"][profile].get("artikel", [])]
        cells = {}
        for label, has in CARRIES.items():
            carrying = [key for key in links if has(ids_of(key[1]))]
            right = sum(1 for key in carrying if grades.get(key) == 2)
            gold = result["pool"][label]
            p, r = (right / len(carrying) if carrying else 0.0), (right / gold if gold else 0.0)
            cells[label] = {
                "anzahl": len(carrying),
                "richtig": right,
                "note0": sum(1 for key in carrying if grades.get(key, 0) == 0),
                "p": round(p, 4),
                "r": round(r, 4),
                "f1": round(2 * p * r / (p + r) if p + r else 0.0, 4),
            }
        result["profile"][profile] = cells
    result["richtig_ohne_gnd"] = sorted({key[1] for key in right_pool if not CARRIES["GND"](ids_of(key[1]))})
    return result


def main() -> None:
    out, service_path, m36_path, *grade_paths = sys.argv[1:]
    service = {row["node_id"]: row for row in json.loads(Path(service_path).read_text(encoding="utf-8"))["materialien"]}
    m36 = {
        row["node_id"]: row
        for row in json.loads(Path(m36_path).read_text(encoding="utf-8"))["materialien"]
        if "wege" in row
    }
    service = {node: row for node, row in service.items() if node in m36}
    report = {
        "zim": wikipedia.id,
        "wikidata_index": index.meta(),
        "materialtexte": len(service),
        "noten": {Path(path).name: evaluate(service, m36, grades_of(path)) for path in grade_paths},
    }
    report["kennungen"] = {
        title: None if ids is None else {"wikidata": ids.wikidata, "gnd": ids.gnd, "gnd_art": ids.gnd_kind,
                                         "viaf": ids.viaf, "dbpedia": ids.dbpedia}
        for title, ids in sorted(cache.items())
    }  # fmt: skip
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, result in report["noten"].items():
        print(f"\n=== {name}: Pool Note 2 {result['pool']}, GND-Arten {result['gnd_arten']}")
        for profile, cells in result["profile"].items():
            print(f"{profile}:")
            for label, c in cells.items():
                scores = f"P {c['p']:.2f}  R {c['r']:.2f}  F1 {c['f1']:.2f}"
                print(f"  {label:18s} {c['anzahl']:4d}  {scores}  Note 0 {c['note0']}")
        print(f"richtig, ohne GND ({len(result['richtig_ohne_gnd'])}): {result['richtig_ohne_gnd']}")


if __name__ == "__main__":
    main()
