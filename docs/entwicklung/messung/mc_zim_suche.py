"""Search speed of the Wikipedia archive through the service's ZimArchive (project venv, development machine).

A fresh process opens the archive; the first title suggestion and the first full-text search are timed alone
("first call" - the operating system may still hold parts of the file in its cache), then each is repeated with
other queries and the median is taken. The full-text queries have the shape build_corpus sends: the topic title
and the first search terms of a block.

Usage: python mc_zim_suche.py <out.json>
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from app.sources.zim.archive import ZimArchive

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

WIKIPEDIA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data\wikipedia_de_all_nopic_2026-01.zim")
TITLES = ["Photosynthese", "Demokratie", "Bruchrechnung", "Sinfonie", "Plattentektonik", "Gedicht", "Klimawandel",
          "Programmiersprache", "Ökosystem", "Wasserkreislauf"]
SEARCHES = [f"{title} Beruf Ausbildung Berufsfeld" for title in TITLES] + [
    f"{title} Unterricht Schule Lehrplan" for title in TITLES]


def timed(call) -> tuple[float, object]:
    started = time.perf_counter()
    result = call()
    return (time.perf_counter() - started) * 1000, result


opened_ms, archive = timed(lambda: ZimArchive(WIKIPEDIA))
first_suggest_ms, _ = timed(lambda: archive.suggest("Optik", 10))
first_search_ms, hits = timed(lambda: archive.search("Optik Brechung Linse", 4))
suggestions = [timed(lambda t=t: archive.suggest(t, 10)) for t in TITLES]
searches = [timed(lambda q=q: archive.search(q, 4)) for q in SEARCHES]
suggest_ms, search_ms = [ms for ms, _ in suggestions], [ms for ms, _ in searches]
result = {
    "archiv": WIKIPEDIA.name,
    "oeffnen_ms": round(opened_ms, 1),
    "erster_titelvorschlag_ms": round(first_suggest_ms, 1),
    "erste_volltextsuche_ms": round(first_search_ms, 1),
    "erste_volltextsuche_treffer": hits,
    "titelvorschlag_median_ms": round(statistics.median(suggest_ms), 1),
    "titelvorschlag_max_ms": round(max(suggest_ms), 1),
    "volltextsuche_median_ms": round(statistics.median(search_ms), 1),
    "volltextsuche_max_ms": round(max(search_ms), 1),
    "wiederholungen": {"titelvorschlag": len(suggest_ms), "volltextsuche": len(search_ms)},
    "ohne_treffer": {"titelvorschlag": sum(1 for _, hits in suggestions if not hits),
                     "volltextsuche": sum(1 for _, hits in searches if not hits)},
}
Path(sys.argv[1]).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=1))
