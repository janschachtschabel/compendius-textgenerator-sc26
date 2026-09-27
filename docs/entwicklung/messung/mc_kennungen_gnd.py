"""M42 a: can local GND data close the GND gap of /entities - the correct articles without a Normdaten block?

Two ways, both local, both on the GND dumps of the DNB (CC0, data.dnb.de/opendata, Turtle): (A) the Wikidata number
of the article (M41, local index) -> the GND record that names this item with owl:sameAs; (B) the title of the
article -> the GND record whose preferred or variant name it is (case-insensitive; "Folge (Mathematik)" is asked as
"Folge <Mathematik>" as well, the GND's form of a qualifier). Each way is first held against the correct articles whose
GND the Normdaten block already gives: how often does it find that very number? Then it is applied to the correct
articles without one; what it proposes there goes to two blind raters. No network; writes titles, GND numbers, GND
names and definitions (CC0), no article text.

Usage (project venv, from the project folder):
python docs/entwicklung/messung/mc_kennungen_gnd.py <out.json> <m41_kennungen.json> <m36_entitaeten.json>
    <noten.yaml> <gnd.ttl.gz> [<gnd.ttl.gz> ...]
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SUBJECT_RE = re.compile(r"^<https://d-nb\.info/gnd/([0-9X-]+)>\s+(.*)$")
STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
WIKIDATA_RE = re.compile(r"<http://www\.wikidata\.org/entity/(Q\d+)>")
PREFERRED = "gndo:preferredNameFor"
VARIANT = "gndo:variantNameFor"


def _objects(pred: str, rest: str, record: dict[str, Any]) -> None:
    if pred == "a":
        record["art"] = rest.split(";")[0].split(",")[0].strip().removeprefix("gndo:")
    elif pred.startswith(PREFERRED):
        record["namen"] += [s.replace('\\"', '"') for s in STRING_RE.findall(rest)]
    elif pred.startswith(VARIANT):
        record["varianten"] += [s.replace('\\"', '"') for s in STRING_RE.findall(rest)]
    elif pred == "owl:sameAs":
        record["wikidata"] += WIKIDATA_RE.findall(rest)
    elif pred == "gndo:definition":
        record["definition"] = " ".join(STRING_RE.findall(rest))[:300]


def read_gnd(paths: list[str]) -> dict[str, dict[str, Any]]:
    """GND number -> kind, names, variants, Wikidata items, definition; read line by line from Turtle dumps."""
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        subject: dict[str, Any] | None = None
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("<"):
                    match = SUBJECT_RE.match(line)
                    subject = None
                    if match and "/about>" not in line.split()[0]:
                        subject = records.setdefault(
                            match.group(1),
                            {"art": "", "namen": [], "varianten": [], "wikidata": [], "definition": ""},
                        )
                        head = match.group(2).split(None, 1)
                        if len(head) == 2:
                            _objects(head[0], head[1], subject)
                elif subject is not None and line.startswith("  "):
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        _objects(parts[0], parts[1], subject)
    return records


def _forms(title: str) -> list[str]:
    forms = [title]
    if match := re.fullmatch(r"(.+?) \((.+)\)", title):
        forms.append(f"{match.group(1)} <{match.group(2)}>")
    return [form.casefold() for form in forms]


def main() -> None:
    out, m41_path, m36_path, grades_path, *dumps = sys.argv[1:]
    ids = json.loads(Path(m41_path).read_text(encoding="utf-8"))["kennungen"]
    m36 = json.loads(Path(m36_path).read_text(encoding="utf-8"))["materialien"]
    grades = {
        (e["node_id"], e["artikel"]): int(e["note"])
        for e in yaml.safe_load(Path(grades_path).read_text("utf-8"))["noten"]
    }
    right = sorted({t for row in m36 if "wege" in row for t in row["pool"] if grades.get((row["node_id"], t)) == 2})
    gnd = read_gnd(dumps)
    by_item: dict[str, set[str]] = defaultdict(set)
    by_name: dict[str, set[str]] = defaultdict(set)
    for number, record in gnd.items():
        for item in record["wikidata"]:
            by_item[item].add(number)
        for name in record["namen"] + record["varianten"]:
            by_name[name.casefold()].add(number)

    def way_a(title: str) -> set[str]:
        item = (ids.get(title) or {}).get("wikidata")
        return set(by_item.get(item, ())) if item else set()

    def way_b(title: str) -> set[str]:
        return set().union(*(by_name.get(form, set()) for form in _forms(title)))

    report: dict[str, Any] = {"gnd_saetze": len(gnd), "richtige_artikel": len(right), "wege": {}}
    known = [t for t in right if (ids.get(t) or {}).get("gnd")]
    gaps = [t for t in right if not (ids.get(t) or {}).get("gnd")]
    for name, way in (("A_wikidata", way_a), ("B_name", way_b)):
        hits = {t: sorted(way(t)) for t in known}
        found = [t for t in known if hits[t]]
        unique = [t for t in found if len(hits[t]) == 1]
        same = [t for t in unique if hits[t][0] == ids[t]["gnd"]]
        other = [(t, ids[t]["gnd"], hits[t]) for t in unique if hits[t][0] != ids[t]["gnd"]]
        proposed = {t: sorted(way(t)) for t in gaps}
        report["wege"][name] = {
            "bekannt": {"artikel": len(known), "gefunden": len(found), "eindeutig": len(unique), "gleich": len(same),
                        "anders": other, "mehrdeutig": [(t, hits[t]) for t in found if len(hits[t]) > 1]},
            "luecke": {"artikel": len(gaps), "gefunden": sum(1 for t in gaps if proposed[t]),
                       "eindeutig": sum(1 for t in gaps if len(proposed[t]) == 1),
                       "vorschlaege": {t: [{"gnd": n, **{k: gnd[n][k] for k in ("art", "namen", "definition")}}
                                           for n in proposed[t]] for t in gaps if proposed[t]}},
        }  # fmt: skip
        k, g = report["wege"][name]["bekannt"], report["wege"][name]["luecke"]
        print(
            f"{name}: bekannte GND {k['artikel']}: gefunden {k['gefunden']}, eindeutig {k['eindeutig']}, "
            f"gleich {k['gleich']}, anders {len(k['anders'])} | Lücke {g['artikel']}: gefunden {g['gefunden']}, "
            f"eindeutig {g['eindeutig']}"
        )
        for title, own, theirs in k["anders"][:8]:
            print(f"   anders: {title}: Normdaten {own}, Weg {theirs} {[gnd[n]['namen'][:1] for n in theirs]}")
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
