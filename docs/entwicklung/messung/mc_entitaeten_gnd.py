"""How many entities of POST /api/v2/entities could carry a GND number from the archive alone (M18).

German Wikipedia ends most articles with a Normdaten block, and the Kiwix dump keeps it: the kind of the record
(Person, Sachbegriff, Geografikum, Körperschaft, Werk, ...) and the GND number, often VIAF and LCCN beside it.
The dump has no Wikidata numbers (docs/umbau.md). This counts, for the entities the endpoint links today, how
many articles have such a block and a GND number in it - no download, no network.

Texts: the opening of the main article of each of the 20 topics of M1 (hauptartikel.yaml, art normal), up to
2000 characters, recognised by the dictionary way of the endpoint and linked as the endpoint links (the spaCy
model lives in the image only; a name it finds links through the same lookup). Writes entity titles and numbers,
no article text.

With --lobid <n> it also checks n GND numbers, drawn with a fixed seed and every Normdaten kind present, against
lobid-gnd (the hbz service over the GND, one request a second): does the record name what the article is about?
That is the only step with network, and it sends nothing but the numbers.

Usage (project venv, from the project root):
python docs/entwicklung/messung/mc_entitaeten_gnd.py <out.json> [--lobid <n> <sample.json>]
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

import yaml

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.api.v2.entities import _link  # the endpoint's own linking, not a copy of it
from app.cli_common import cli_service
from app.knowledge.recognise import mentions_from_titles, merge

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
EVAL = Path("eval") / "artikelwahl" / "hauptartikel.yaml"
TEXT_CHARS = 2000
MAX_ENTITIES = 50  # the endpoint's default
NORMDATEN_RE = re.compile(r"Normdaten(?:&nbsp;|\s)\(([^)]+)\)")
GND_RE = re.compile(r"d-nb\.info/gnd/([0-9X-]+)")
VIAF_RE = re.compile(r"viaf\.org/viaf/(\d+)")
SEED = 20260924
USER_AGENT = "kompendium-messung/1.0 (+https://github.com/janschachtschabel/compendius-textgenerator-sc26)"


def normdaten(html: str) -> dict:
    """Kind, GND and VIAF of the Normdaten block, read only inside that block."""
    start = html.find('id="normdaten"')
    if start < 0:
        return {}
    block = html[start : start + 3000]
    found = {"art": NORMDATEN_RE.search(block), "gnd": GND_RE.search(block), "viaf": VIAF_RE.search(block)}
    return {key: match.group(1) for key, match in found.items() if match}


service = cli_service(ZIMS)
registry = service.registry
wiki = registry.primary_archive
assert wiki is not None
topics = [e["anfrage"] for e in yaml.safe_load(EVAL.read_text(encoding="utf-8"))["anfragen"] if e["art"] == "normal"]

rows = []
for topic in topics:
    main = registry.resolve_topic(topic)
    article = wiki.read(main.title) if main.title else None
    if article is None:
        continue
    text = wiki.parse(article).text[:TEXT_CHARS]
    mentions = merge(mentions_from_titles(registry.archives, text))[:MAX_ENTITIES]
    entities = []
    for mention in mentions:
        linked = _link(registry.archives, mention)
        if linked is None:  # the endpoint drops a dictionary term behind a disambiguation page
            continue
        page = wiki.read(linked.title) if linked.project == "wikipedia" else None
        entities.append(
            {
                "text": mention.text,
                "titel": linked.title,
                "projekt": linked.project,
                "art": linked.kind,
                **({"normdaten": normdaten(page.html)} if page else {}),
            }
        )
    rows.append({"thema": topic, "hauptartikel": main.title, "begriffe": len(mentions), "entitaeten": entities})

Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
entities = [e for r in rows for e in r["entitaeten"]]
wikipedia = [e for e in entities if e["projekt"] == "wikipedia"]
with_block = [e for e in wikipedia if e.get("normdaten")]
with_gnd = [e for e in with_block if "gnd" in e["normdaten"]]
print(
    f"Texte {len(rows)}, Begriffe {sum(r['begriffe'] for r in rows)}, verknüpft {len(entities)} "
    f"(Wikipedia {len(wikipedia)}); mit Normdaten {len(with_block)}, mit GND {len(with_gnd)}, "
    f"mit VIAF {sum('viaf' in e['normdaten'] for e in with_block)}"
)
print("GND-Art:", dict(Counter(e["normdaten"].get("art") for e in with_gnd).most_common()))
print("ohne GND nach Art des Dienstes:", dict(Counter(e["art"] or "Sache" for e in wikipedia if e not in with_gnd)))
print("mit GND nach Art des Dienstes:", dict(Counter(e["art"] or "Sache" for e in with_gnd)))


def sample(entities: list[dict], size: int) -> list[dict]:
    """Up to eight subject headings and six of every other kind, then random ones, all with a fixed seed."""
    rng = random.Random(SEED)  # noqa: S311 - a reproducible sample, not a secret
    unique = list({e["normdaten"]["gnd"]: e for e in entities}.values())
    by_kind: dict[str, list[dict]] = {}
    for entity in unique:
        by_kind.setdefault(entity["normdaten"].get("art", ""), []).append(entity)
    picked = []
    for kind, group in by_kind.items():
        rng.shuffle(group)
        picked += group[: 8 if kind == "Sachbegriff" else 6]
    rest = [e for e in unique if e not in picked]
    rng.shuffle(rest)
    return (picked + rest)[:size]


if "--lobid" in sys.argv:
    size, sample_path = int(sys.argv[sys.argv.index("--lobid") + 1]), Path(sys.argv[sys.argv.index("--lobid") + 2])
    checked = []
    for entity in sample(with_gnd, size):
        gnd = entity["normdaten"]["gnd"]
        request = urllib.request.Request(
            f"https://lobid.org/gnd/{gnd}.json", headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - a fixed https host
            record = json.load(response)
        checked.append(
            {
                "text": entity["text"],
                "titel": entity["titel"],
                "art": entity["normdaten"].get("art"),
                "gnd": gnd,
                "gnd_name": record.get("preferredName"),
                "gnd_typ": [t for t in record.get("type", []) if t != "AuthorityResource"],
                "wikidata": [s["id"] for s in record.get("sameAs", []) if "wikidata.org" in s.get("id", "")][:1],
            }
        )
        time.sleep(1.0)
    sample_path.write_text(json.dumps(checked, ensure_ascii=False, indent=1), encoding="utf-8")
    for row in checked:
        print(f"{row['text'][:24]:24} -> {row['titel'][:30]:30} | {row['art'] or '-':12} | GND: {row['gnd_name']}")
