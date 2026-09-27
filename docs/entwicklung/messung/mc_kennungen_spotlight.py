"""M42 c: DBpedia Spotlight (German model) as a local linker for llm-free, on the texts of M36's 40 materials.

Spotlight annotates a text with DBpedia resources; the German model names ``http://de.dbpedia.org/resource/<title>``.
Each title is read in the Wikipedia archive the way the endpoint reads a linked article: a redirect leads to its
target, a disambiguation page drops out. What comes out is compared with M36's grades (an article counts as right
with grade 2); articles M36 never graded are listed for blind raters, and ``--noten-extra`` adds their grades. The
profiles of D62 (``--dienst``) are counted again against the same pool, grown by what Spotlight found right.

The texts come from M36's rating sheet (title, description and keywords of each material, as the endpoint read them),
which holds text and stays out of the repository. Spotlight runs in Docker on this machine
(dbpedia/dbpedia-spotlight, model 2022.03.01), so nothing leaves it. Writes titles and counts, no text.

Usage (project venv, from the project folder):
python docs/entwicklung/messung/mc_kennungen_spotlight.py <out.json> <m36_bogen.json> <m36_entitaeten.json>
    <noten.yaml> --dienst <m36_entitaeten_dienst.json> [--api …/rest/annotate] [--confidence 0.35,0.5]
    [--noten-extra <extra.yaml> ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import httpx
import yaml

from app.sources.zim.registry import ZimRegistry

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [DATA / "wikipedia_de_all_nopic_2026-01.zim", DATA / "klexikon_de_all_maxi_2026-08.zim"]
RESOURCE = "/resource/"


def grades_of(paths: list[str]) -> dict[tuple[str, str], int]:
    grades: dict[tuple[str, str], int] = {}
    for path in paths:
        for entry in yaml.safe_load(Path(path).read_text(encoding="utf-8"))["noten"]:
            grades.setdefault((entry["node_id"], entry["artikel"]), int(entry["note"]))
    return grades


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("bogen")
    parser.add_argument("m36")
    parser.add_argument("noten")
    parser.add_argument("--api", default="http://127.0.0.1:2222/rest/annotate")
    parser.add_argument("--confidence", default="0.35,0.5")
    parser.add_argument("--noten-extra", nargs="*", default=[])
    parser.add_argument("--dienst", required=True)
    args = parser.parse_args()
    texts = {row["node_id"]: row["text"] for row in json.loads(Path(args.bogen).read_text(encoding="utf-8"))}
    m36 = {
        r["node_id"]: r for r in json.loads(Path(args.m36).read_text(encoding="utf-8"))["materialien"] if "wege" in r
    }
    grades = grades_of([args.noten, *args.noten_extra])
    wikipedia = next(a for a in ZimRegistry(ZIMS).archives if a.id.startswith("wikipedia"))
    looked: dict[str, str | None] = {}

    def article(title: str) -> str | None:
        """The archive's article for a title as the endpoint links it: redirects followed, no disambiguation."""
        if title not in looked:
            found = wikipedia.read_article(title)
            looked[title] = None if found is None or wikipedia.parse(found).is_disambiguation else found.title
        return looked[title]

    client = httpx.Client(timeout=120.0)
    report: dict = {"confidence": {}}
    ungraded: dict[tuple[str, str], None] = {}
    for confidence in (float(value) for value in args.confidence.split(",")):
        rows, seconds = {}, []
        for node_id, text in texts.items():
            if node_id not in m36:
                continue
            started = time.monotonic()
            response = client.post(
                args.api, data={"text": text, "confidence": confidence}, headers={"Accept": "application/json"}
            )
            response.raise_for_status()
            seconds.append(time.monotonic() - started)
            resources = response.json().get("Resources") or []
            titles = [
                unquote(r["@URI"].split(RESOURCE, 1)[1]).replace("_", " ") for r in resources if RESOURCE in r["@URI"]
            ]
            linked = list(dict.fromkeys(t for t in (article(title) for title in titles) if t))
            rows[node_id] = {"dbpedia": list(dict.fromkeys(titles)), "artikel": linked}
            ungraded.update({(node_id, t): None for t in linked if (node_id, t) not in grades})
        right = {(n, t) for n, r in m36.items() for t in r["pool"] if grades.get((n, t)) == 2}
        right |= {(n, t) for n, row in rows.items() for t in row["artikel"] if grades.get((n, t)) == 2}
        found = [(n, t) for n, row in rows.items() for t in row["artikel"]]
        hits = sum(1 for key in found if grades.get(key) == 2)
        p = hits / len(found) if found else 0.0
        r = hits / len(right) if right else 0.0
        report["confidence"][str(confidence)] = {
            "artikel": len(found),
            "richtig": hits,
            "note0": sum(1 for key in found if grades.get(key) == 0),
            "ohne_note": sum(1 for key in found if key not in grades),
            "pool_note2": len(right),
            "p": round(p, 4),
            "r": round(r, 4),
            "f1": round(2 * p * r / (p + r) if p + r else 0.0, 4),
            "sekunden_median": round(sorted(seconds)[len(seconds) // 2], 3) if seconds else None,
            "materialien": rows,
        }
        service = {r["node_id"]: r for r in json.loads(Path(args.dienst).read_text(encoding="utf-8"))["materialien"]}
        for profile in ("llm-free", "balanced"):
            theirs = [(n, t) for n in rows for t in service[n]["profile"][profile].get("artikel", [])]
            got = sum(1 for key in theirs if grades.get(key) == 2)
            tp, tr = (got / len(theirs) if theirs else 0.0), (got / len(right) if right else 0.0)
            report["confidence"][str(confidence)][f"vergleich_{profile}"] = {
                "artikel": len(theirs), "p": round(tp, 4), "r": round(tr, 4),
                "f1": round(2 * tp * tr / (tp + tr) if tp + tr else 0.0, 4),
            }  # fmt: skip
            print(f"   {profile} gegen denselben Pool: P {tp:.2f}, R {tr:.2f}")
        c = report["confidence"][str(confidence)]
        print(
            f"confidence {confidence}: {c['artikel']} Artikel, P {p:.2f}, R {r:.2f}, F1 {c['f1']:.2f}, Note 0 "
            f"{c['note0']}, ohne Note {c['ohne_note']}, Pool {len(right)}, {c['sekunden_median']} s je Text"
        )
    report["ohne_note"] = [{"node_id": n, "artikel": t} for n, t in ungraded]
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
