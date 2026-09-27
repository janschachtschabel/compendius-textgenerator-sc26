"""M42 b: which linked articles of /entities would get a DBpedia URI that resolves - through their English article.

The endpoint builds ``http://de.dbpedia.org/resource/<German title>``; that server no longer answers (M42). DBpedia's
live resources are ``http://dbpedia.org/resource/<English title>``, one per article of the English Wikipedia. The
English title comes from the dewiki table ``langlinks`` (language ``en``), joined by page id to the table ``page``;
both are read from dumps of the same run with the SQL reader of the Wikidata index. Counts per profile (the articles
the endpoint linked after D62 for the 40 material texts) and for the correct articles of M36's pool. No network;
writes titles and English titles, no text.

Usage (project venv, from the project folder):
python docs/entwicklung/messung/mc_kennungen_dbpedia.py <out.json> <m36_entitaeten_dienst.json> <m36_entitaeten.json>
    <noten.yaml> <dewiki-…-page.sql.gz> <dewiki-…-langlinks.sql.gz>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from app.sources.wikidata.index import ARTICLE_NAMESPACE, _rows

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

PROFILES = ("llm-free", "balanced", "mit Prüfung")


def main() -> None:
    out, service_path, m36_path, grades_path, page_dump, langlinks_dump = sys.argv[1:]
    service = json.loads(Path(service_path).read_text(encoding="utf-8"))["materialien"]
    m36 = {row["node_id"]: row for row in json.loads(Path(m36_path).read_text("utf-8"))["materialien"] if "wege" in row}
    grades = {
        (e["node_id"], e["artikel"]): int(e["note"])
        for e in yaml.safe_load(Path(grades_path).read_text("utf-8"))["noten"]
    }
    linked = {
        profile: [
            (row["node_id"], t) for row in service if row["node_id"] in m36 for t in row["profile"][profile]["artikel"]
        ]
        for profile in PROFILES
    }
    right = {(n, t) for n, row in m36.items() for t in row["pool"] if grades.get((n, t)) == 2}
    wanted = {t for pairs in linked.values() for _, t in pairs} | {t for _, t in right}
    info: dict[str, str] = {}
    page_ids = {
        title.replace("_", " "): int(page_id)
        for page_id, namespace, title in _rows(
            Path(page_dump), "page", ("page_id", "page_namespace", "page_title"), info
        )
        if namespace == ARTICLE_NAMESPACE and title and title.replace("_", " ") in wanted
    }
    wanted_ids = set(page_ids.values())
    english = {
        int(page_id): title.replace("_", " ")
        for page_id, lang, title in _rows(Path(langlinks_dump), "langlinks", ("ll_from", "ll_lang", "ll_title"), info)
        if lang == "en" and page_id and int(page_id) in wanted_ids and title
    }

    def en_of(title: str) -> str | None:
        page_id = page_ids.get(title)
        return english.get(page_id) if page_id is not None else None

    report: dict = {"dump": info.get("dump"), "profile": {}, "englisch": {t: en_of(t) for t in sorted(wanted)}}
    for profile, pairs in [*linked.items(), ("richtig (Pool, Note 2)", sorted(right))]:
        with_en = [key for key in pairs if en_of(key[1])]
        correct = [key for key in with_en if grades.get(key) == 2]
        report["profile"][profile] = {
            "artikel": len(pairs),
            "mit_englischem_artikel": len(with_en),
            "davon_richtig": len(correct),
            "ohne_seite_im_dump": sorted({t for _, t in pairs if t not in page_ids}),
        }
        share = len(with_en) / len(pairs) if pairs else 0.0
        counts = f"{len(pairs):4d} Artikel, {len(with_en):4d} mit englischem ({share:.0%}), richtig {len(correct)}"
        print(f"{profile:24s} {counts}")
    missing = sorted({t for _, t in right if not en_of(t)})
    print(f"richtige ohne englischen Artikel ({len(missing)}): {missing}")
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
