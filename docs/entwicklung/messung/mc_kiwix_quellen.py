"""Further Kiwix archives as sources (M84, project venv, no LLM): what each archive of the Wiki family brings.

Two questions per archive - Klexikon as the reference the service already reads, then Wikibooks, Wikiversity,
Wiktionary, Wikisource, Wikiquote and Wikivoyage:

1. Coverage. The article of the same title as each expected main article of the gold (eval/artikelwahl), the one
   way another archive enters a corpus today; and the first five full-text hits for the collection and aspect topics
   of M82, kept like the service keeps a hit (the topic named in title or lead), as a search over the archive would
   bring them.
2. The service's own flow. The 20 normal topics of the gold, part 1 with the rules (llm-free, hybrid_light, 30,000
   characters), once with Wikipedia and Klexikon and once more with each further archive alone and with all of them:
   the pages of the further archives in the corpus, their paragraphs and the paragraphs the text prints from them.

The output holds titles, counts and headings, no text; the beginnings of the pages and of the printed paragraphs go
to the pool, which stays outside the repository (for the labels in m84_einordnung.yaml). The six further archives
were deleted after M84 (D99); mc_kiwix_laden.py fetches them again into kompendium-test/data/zusatz/.

Usage: python mc_kiwix_quellen.py <out.json> <pool.json>
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.knowledge.topic import TopicMention  # noqa: E402
from app.sources.zim.archive import ZimArchive  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[3]
DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
EXTRA_DATA = DATA / "zusatz"
ARCHIVES = {
    "wikipedia": DATA / "wikipedia_de_all_nopic_2026-01.zim",
    "klexikon": DATA / "klexikon_de_all_maxi_2026-08.zim",
    "wikibooks": EXTRA_DATA / "wikibooks_de_all_nopic" / "wikibooks_de_all_nopic_2026-01.zim",
    "wikiversity": EXTRA_DATA / "wikiversity_de_all_nopic" / "wikiversity_de_all_nopic_2026-07.zim",
    "wiktionary": EXTRA_DATA / "wiktionary_de_all_nopic" / "wiktionary_de_all_nopic_2026-07.zim",
    "wikisource": EXTRA_DATA / "wikisource_de_all_nopic" / "wikisource_de_all_nopic_2026-09.zim",
    "wikiquote": EXTRA_DATA / "wikiquote_de_all_nopic" / "wikiquote_de_all_nopic_2026-07.zim",
    "wikivoyage": EXTRA_DATA / "wikivoyage_de_all_nopic" / "wikivoyage_de_all_nopic_2026-07.zim",
}
COMPARED = ["klexikon", "wikibooks", "wikiversity", "wiktionary", "wikisource", "wikiquote", "wikivoyage"]
FURTHER = COMPARED[1:]
HITS = 5
M2V = "JanSchachtschabel/m2v-gte-256-edu"
TARGET_LENGTH = 30_000
VARIANTS = {"standard": [], **{name: [name] for name in FURTHER}, "alle": FURTHER}

out_path, pool_path = Path(sys.argv[1]), Path(sys.argv[2])
gold = yaml.safe_load((REPO / "eval/artikelwahl/hauptartikel.yaml").read_text("utf-8"))["anfragen"]
titles = list(dict.fromkeys(title for entry in gold for title in entry.get("erwartet") or []))
normal = [entry["anfrage"] for entry in gold if entry["art"] == "normal"]
inputs = json.loads((REPO / "docs/entwicklung/messung/ergebnisse/m82_eingaben.json").read_text("utf-8"))["lehrplan"]
searched = [f"{kind}:{topic}" for kind in ("gruppe", "aspekt") for topic in inputs[kind]]
pool: dict[str, dict] = defaultdict(dict)


def describe(archive: ZimArchive) -> dict:
    scraper = archive._meta("Scraper")  # noqa: SLF001 - the one metadata key the wrapper does not read itself
    return {**archive.snapshot(), "scraper": scraper, "bytes": archive.path.stat().st_size}


def page(archive: ZimArchive, name: str, title: str) -> dict | None:
    """One page as the service reads it: ``None`` when missing; a disambiguation is marked, not counted."""
    article = archive.read(title)
    if article is None:
        return None
    parsed = archive.parse(article)
    paragraphs = [p.text for s in parsed.sections for p in s.paragraphs]
    pool[f"{name}:{article.title}"] = {"anfang": " ".join(" ".join(paragraphs[:3]).split())[:600]}
    return {
        "titel": article.title,
        "begriffsklaerung": parsed.is_disambiguation,
        "absaetze": len(paragraphs),
        "zeichen": sum(len(p) for p in paragraphs),
        "ueberschriften": [s.heading for s in parsed.sections if s.heading][:12],
    }


def coverage(archives: dict[str, ZimArchive]) -> dict:
    same_title = {title: {name: page(archives[name], name, title) for name in COMPARED} for title in titles}
    search: dict[str, dict] = {}
    for key in searched:
        topic = key.split(":", 1)[1]
        mention = TopicMention.of(topic)
        row = {}
        for name in COMPARED:
            hits = []
            for title in archives[name].search(topic, HITS):
                found = page(archives[name], name, title)
                if found is None or found["begriffsklaerung"]:
                    continue
                source = archives[name].to_source(archives[name].read(title), is_primary=False)
                hits.append({**found, "behalten": mention.found_in(f"{source.title} {source.lead_text}")})
            row[name] = hits
        search[key] = row
    return {"gleicher_titel": same_title, "volltextsuche": search}


def flow(variant: str, further: list[str]) -> dict:
    """Part 1 of the 20 normal topics with the rules, over Wikipedia, Klexikon and ``further``."""
    service = cli_service([str(ARCHIVES[name]) for name in ["wikipedia", "klexikon", *further]])
    service.settings.model2vec_path = M2V
    rows = {}
    for topic in normal:
        prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
        matched = service.match(prepared, "hybrid_light", TARGET_LENGTH)
        content = {slot.id: slot.title for slot in prepared.template.content_slots()}
        printed: dict[str, list[str]] = defaultdict(list)
        printed_text: dict[str, list[str]] = defaultdict(list)
        for slot_id, items in matched.assignment.assigned.items():
            for item in items:
                printed[item.chunk.source_id].append(content.get(slot_id, slot_id))
                printed_text[item.chunk.source_id].append(item.chunk.text[:300])
        chunks = Counter(chunk.source_id for chunk in prepared.chunks)
        pages = []
        for source in prepared.sources:
            if source.project == "wikipedia":  # Klexikon stays in: what the reference archive prints today
                continue
            pages.append({
                "projekt": source.project, "titel": source.title, "herkunft": source.origin,
                "absaetze": chunks.get(source.source_id, 0), "gedruckt": len(printed.get(source.source_id, [])),
                "bausteine": dict(Counter(printed.get(source.source_id, []))),
            })
            pool[f"ablauf:{variant}:{topic}:{source.project}:{source.title}"] = {
                "gedruckt": printed_text.get(source.source_id, [])[:5],
            }
        rows[topic] = {
            "bausteine_gefuellt": sum(
                1 for slot, items in matched.assignment.assigned.items() if slot in content and items
            ),
            "gedruckt": sum(len(v) for v in printed.values()),
            "artikel": [f"{s.project}:{s.title}" for s in prepared.sources],
            "seiten": pages,  # the pages from archives other than Wikipedia, Klexikon included
        }
    return rows


archives = {name: ZimArchive(path) for name, path in ARCHIVES.items()}
result = {"archive": {name: describe(a) for name, a in archives.items()}, "abdeckung": coverage(archives)}
result["ablauf"] = {variant: flow(variant, further) for variant, further in VARIANTS.items()}
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=1), "utf-8")

print("Archive:", {n: (a["date"], a["articles"], a["scraper"]) for n, a in result["archive"].items()})
same = result["abdeckung"]["gleicher_titel"]
print(f"\nGleicher Titel, {len(titles)} erwartete Hauptartikel (ohne Begriffsklärung):")
for name in COMPARED:
    found = [t for t, row in same.items() if row[name] and not row[name]["begriffsklaerung"]]
    print(f"  {name:<12} {len(found):>2}  {', '.join(found)}")
print(f"\nVolltextsuche, {len(searched)} Sammel- und Aspektthemen, je Archiv {HITS} Treffer:")
for name in COMPARED:
    hits = [h for row in result["abdeckung"]["volltextsuche"].values() for h in row[name]]
    kept = [h for h in hits if h["behalten"]]
    topics = sum(any(h["behalten"] for h in row[name]) for row in result["abdeckung"]["volltextsuche"].values())
    print(f"  {name:<12} Treffer {len(hits):>3}, behalten {len(kept):>3} bei {topics:>2} Themen")
print(f"\nAblauf des Dienstes, {len(normal)} Themen, llm-free, {TARGET_LENGTH} Zeichen:")
base = result["ablauf"]["standard"]
for variant, rows in result["ablauf"].items():
    for project in ["klexikon", *(VARIANTS[variant] or [])]:
        pages = [p for r in rows.values() for p in r["seiten"] if p["projekt"] == project]
        print(f"  {variant:<12} {project:<12} Seiten {len(pages):>2} bei"
              f" {sum(1 for r in rows.values() if any(p['projekt'] == project for p in r['seiten'])):>2} Themen,"
              f" Absätze {sum(p['absaetze'] for p in pages):>4}, gedruckt {sum(p['gedruckt'] for p in pages):>3}")
    print(f"  {variant:<12} {'gesamt':<12} Bausteine {sum(r['bausteine_gefuellt'] for r in rows.values()):>3}"
          f" (Standard {sum(r['bausteine_gefuellt'] for r in base.values())}),"
          f" gedruckt {sum(r['gedruckt'] for r in rows.values()):>4}"
          f" (Standard {sum(r['gedruckt'] for r in base.values())})")
