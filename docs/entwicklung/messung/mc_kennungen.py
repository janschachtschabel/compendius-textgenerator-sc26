"""M41, M43: how right the identifiers of POST /api/v2/entities are per profile - Wikidata, DBpedia, GND - from local
data.

No new run: the articles each profile linked for the 40 material texts come from the run through the endpoint after
D62 (m36_entitaeten_dienst.json). For every article the endpoint's own ``identifiers()`` reads GND, Normdaten kind and
VIAF from the ZIM page and the Wikidata number from the local index (``compendium wikidata build``); the DBpedia URI is
built from the title for every article. An identifier is right when its article has grade 2 in M36; recall counts
against the pooled grade-2 articles that carry that identifier. No network. Writes titles, identifiers and counts, no
text.

Since D65 (M43) the same function also gives the DBpedia URI of the English article and, where the Normdaten block
has no GND, the GND from the local GND index. Such a GND is right only when its article has grade 2 and the blind
grade of the pair (title, GND record; M42, ``--gnd-noten``) is 2 as well: the record means what the article means.
Pairs of right articles without such a grade are listed and count as wrong until graded. ``--gnd-noten`` may be given
once per grade file, in the same order (the second rater's GND grades with the second rater's article grades).

Usage (inside the development container, where the archives and the indexes are; PYTHONPATH=/app):
python mc_kennungen.py <out.json> <m36_entitaeten_dienst.json> <m36_entitaeten.json> <noten.yaml> [<noten_zweit.yaml>]
    [--gnd-noten <eval/kennungen/noten_gnd.yaml> [--gnd-noten <eval/kennungen/noten_gnd_zweit.yaml>]]
"""

from __future__ import annotations

import collections
import json
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

from app.knowledge.identifiers import DBPEDIA, Identifiers, identifiers
from app.settings import get_settings
from app.sources.gnd.index import GndIndex
from app.sources.wikidata.index import WikidataIndex
from app.sources.zim.registry import ZimRegistry

PROFILES = ("llm-free", "balanced", "mit Prüfung")  # balanced stands for best-quality too: same way, same articles
CARRIES: dict[str, Callable[[Identifiers | None], bool]] = {
    "Wikipedia/DBpedia": lambda ids: ids is not None,
    "Wikidata": lambda ids: ids is not None and ids.wikidata is not None,
    "GND": lambda ids: ids is not None and ids.gnd is not None,
    "DBpedia über den englischen Artikel": lambda ids: ids is not None and ids.dbpedia.startswith(DBPEDIA),
}

settings = get_settings()
registry = ZimRegistry(settings.zim_path_list) if settings.zim_path_list else ZimRegistry.from_active(settings.zim_dir)
wikipedia = next(archive for archive in registry.archives if archive.id.startswith("wikipedia"))
index = WikidataIndex(settings.wikidata_db_path)
gnd_index = GndIndex(settings.gnd_db_path)
cache: dict[str, Identifiers | None] = {}


def ids_of(title: str) -> Identifiers | None:
    if title not in cache:
        article = wikipedia.read_article(title)
        cache[title] = identifiers(article.title, article.html, index, gnd_index) if article is not None else None
    return cache[title]


def grades_of(path: str) -> dict[tuple[str, str], int]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {(entry["node_id"], entry["artikel"]): int(entry["note"]) for entry in data["noten"]}


def from_index(ids: Identifiers | None) -> bool:
    return ids is not None and ids.gnd_source in ("wikidata", "name")


def cross_check(titles: set[str]) -> dict:
    """Where the Normdaten block names the GND, does each way of the index lead to the same record (as M42 a)?"""
    known = [(title, ids) for title in sorted(titles) if (ids := ids_of(title)) and ids.gnd_source == "normdaten"]
    result: dict = {"bekannt": len(known)}
    for way in ("wikidata", "name"):
        hits = [
            (title, ids.gnd, hit.number)
            for title, ids in known
            if (hit := gnd_index.find("", ids.wikidata) if way == "wikidata" else gnd_index.find(title, None))
        ]
        result[way] = {
            "gefunden": len(hits),
            "gleich": sum(1 for _, number, found in hits if number == found),
            "abweichend": [hit for hit in hits if hit[1] != hit[2]],
        }
    return result


def evaluate(
    service: dict, m36: dict, grades: dict[tuple[str, str], int], gnd_pairs: dict[tuple[str, str], int]
) -> dict:
    def right(label: str, key: tuple[str, str]) -> bool:
        if grades.get(key) != 2:
            return False
        ids = ids_of(key[1])
        if label == "GND" and ids is not None and from_index(ids):  # the index's record must mean the article
            return gnd_pairs.get((key[1], ids.gnd or "")) == 2
        return True

    right_pool = {(node, title) for node in service for title in m36[node]["pool"] if grades.get((node, title)) == 2}
    kinds = collections.Counter(ids.gnd_kind for key in right_pool if (ids := ids_of(key[1])) and ids.gnd)
    unpaired = set()
    for key in right_pool:
        ids = ids_of(key[1])
        if ids is not None and from_index(ids) and (key[1], ids.gnd or "") not in gnd_pairs:
            unpaired.add((key[1], ids.gnd or ""))
    result: dict = {
        "pool": {
            label: sum(1 for key in right_pool if has(ids_of(key[1])) and right(label, key))
            for label, has in CARRIES.items()
        },
        "gnd_arten": dict(kinds.most_common()),
        "gnd_unbenotet": sorted(unpaired),
        "gegenprobe": cross_check({key[1] for key in right_pool}),
        "profile": {},
    }
    for profile in PROFILES:
        links = [(node, title) for node, row in service.items() for title in row["profile"][profile].get("artikel", [])]
        cells = {}
        for label, has in CARRIES.items():
            carrying = [key for key in links if has(ids_of(key[1]))]
            hits = sum(1 for key in carrying if right(label, key))
            gold = result["pool"][label]
            p, r = (hits / len(carrying) if carrying else 0.0), (hits / gold if gold else 0.0)
            cells[label] = {
                "anzahl": len(carrying),
                "richtig": hits,
                "note0": sum(1 for key in carrying if grades.get(key, 0) == 0),
                "p": round(p, 4),
                "r": round(r, 4),
                "f1": round(2 * p * r / (p + r) if p + r else 0.0, 4),
            }
        sources = collections.Counter(ids.gnd_source for key in links if (ids := ids_of(key[1])) and ids.gnd)
        cells["GND nach Herkunft"] = dict(sources.most_common())
        result["profile"][profile] = cells
    result["richtig_ohne_gnd"] = sorted({key[1] for key in right_pool if not CARRIES["GND"](ids_of(key[1]))})
    return result


def filled_gnd(pairs: dict[tuple[str, str], int]) -> dict:
    """The GND numbers the index filled in for any linked article, held against the blind grades of (title, record)."""
    filled = {title: ids for title, ids in cache.items() if ids is not None and from_index(ids)}
    graded = {title: pairs.get((title, ids.gnd or "")) for title, ids in filled.items()}
    return {
        "gefuellt": len(filled),
        "noten": dict(collections.Counter(str(grade) for grade in graded.values())),
        "unbenotet": sorted((title, filled[title].gnd) for title, grade in graded.items() if grade is None),
    }


def main() -> None:
    args = sys.argv[1:]
    gnd_files: list[dict[tuple[str, str], int]] = []
    while "--gnd-noten" in args:
        at = args.index("--gnd-noten")
        data = yaml.safe_load(Path(args[at + 1]).read_text(encoding="utf-8"))
        gnd_files.append({(entry["artikel"], str(entry["gnd"])): int(entry["note"]) for entry in data["noten"]})
        del args[at : at + 2]
    out, service_path, m36_path, *grade_paths = args
    gnd_grades = gnd_files[0] if gnd_files else {}

    def gnd_file(position: int) -> dict[tuple[str, str], int]:
        return gnd_files[min(position, len(gnd_files) - 1)] if gnd_files else {}

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
        "gnd_index": gnd_index.meta(),
        "materialtexte": len(service),
        "noten": {
            Path(path).name: evaluate(service, m36, grades_of(path), gnd_file(position))
            for position, path in enumerate(grade_paths)
        },
    }
    report["kennungen"] = {
        title: None if ids is None else {"wikidata": ids.wikidata, "gnd": ids.gnd, "gnd_art": ids.gnd_kind,
                                         "gnd_herkunft": ids.gnd_source, "viaf": ids.viaf, "dbpedia": ids.dbpedia}
        for title, ids in sorted(cache.items())
    }  # fmt: skip
    report["gnd_aus_dem_index"] = filled_gnd(gnd_grades)
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, result in report["noten"].items():
        print(f"\n=== {name}: Pool Note 2 {result['pool']}, GND-Arten {result['gnd_arten']}")
        for profile, cells in result["profile"].items():
            print(f"{profile}:")
            for label, c in cells.items():
                if "p" not in c:
                    print(f"  {label}: {c}")
                    continue
                scores = f"P {c['p']:.2f}  R {c['r']:.2f}  F1 {c['f1']:.2f}"
                print(f"  {label:36s} {c['anzahl']:4d}  {scores}  Note 0 {c['note0']}")
        print(f"richtig, ohne GND ({len(result['richtig_ohne_gnd'])}): {result['richtig_ohne_gnd']}")
        print(f"GND aus dem Index an richtigen Artikeln, ohne Note: {result['gnd_unbenotet']}")
        print(f"Gegenprobe an bekannten GND: {result['gegenprobe']}")
    print()
    print(f"GND aus dem Index: {report['gnd_aus_dem_index']}")


if __name__ == "__main__":
    main()
