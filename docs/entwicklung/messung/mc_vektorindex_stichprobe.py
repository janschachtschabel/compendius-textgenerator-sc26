"""M87: how big would a paragraph index of the German Wikipedia be? A random sample of articles, parsed like the
service (D101).

Draws random entries of the Wikipedia ZIM until <n> articles (no redirects) are read, parses each with the service's
parser and counts paragraphs, paragraphs of at least 100 characters and characters; times the read and the parse.
Writes the counts and a random sample of 3,000 paragraphs (for mc_vektorindex_tempo.py) to <out.json>.

Usage (project venv): python mc_vektorindex_stichprobe.py <n> <out.json>
"""

from __future__ import annotations

import json
import random
import statistics
import sys
import time
from pathlib import Path

from app.sources.zim.archive import ZimArchive
from app.sources.zim.html import parse_article

sys.stdout.reconfigure(encoding="utf-8")
n, out = int(sys.argv[1]), Path(sys.argv[2])
zim = ZimArchive(Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data\wikipedia_de_all_nopic_2026-01.zim"))
raw = zim._archive  # noqa: SLF001 - the random entries libzim offers
random.seed(84)
rows, redirects, pool = [], 0, []
read_s = parse_s = 0.0
while len(rows) < n:
    entry = raw.get_random_entry()
    if entry.is_redirect:
        redirects += 1
        continue
    started = time.perf_counter()
    html = bytes(entry.get_item().content).decode("utf-8", "replace")
    read_s += time.perf_counter() - started
    started = time.perf_counter()
    parsed = parse_article(html, entry.title)
    parse_s += time.perf_counter() - started
    paragraphs = [p.text for s in parsed.sections for p in s.paragraphs]
    long = [p for p in paragraphs if len(p) >= 100]
    rows.append(
        {
            "absaetze": len(paragraphs),
            "lang": len(long),
            "zeichen": sum(len(p) for p in paragraphs),
            "zeichen_lang": sum(len(p) for p in long),
            "bkl": parsed.is_disambiguation,
        }
    )
    pool.extend(long)

random.shuffle(pool)
summary = {
    "artikel": len(rows),
    "weiterleitungen_gezogen": redirects,
    "begriffsklaerungen": sum(r["bkl"] for r in rows),
    "absaetze_mittel": statistics.mean(r["absaetze"] for r in rows),
    "absaetze_median": statistics.median(r["absaetze"] for r in rows),
    "lange_absaetze_mittel": statistics.mean(r["lang"] for r in rows),
    "zeichen_mittel": statistics.mean(r["zeichen"] for r in rows),
    "zeichen_lang_mittel": statistics.mean(r["zeichen_lang"] for r in rows),
    "zeichen_je_langem_absatz": sum(r["zeichen_lang"] for r in rows) / max(1, sum(r["lang"] for r in rows)),
    "lesen_ms_je_artikel": 1000 * read_s / len(rows),
    "parsen_ms_je_artikel": 1000 * parse_s / len(rows),
    "artikel_im_archiv": zim.article_count,
}
print(json.dumps(summary, ensure_ascii=False, indent=1))
out.write_text(json.dumps({"summary": summary, "absaetze": pool[:3000]}, ensure_ascii=False), "utf-8")
