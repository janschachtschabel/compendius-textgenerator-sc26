"""Which identifiers the entities of POST /api/v2/entities carry, from local data only (M18, D43).

German Wikipedia ends most articles with a Normdaten block, and the Kiwix dump keeps it: the kind of the record
(Person, Sachbegriff, Geografikum, Körperschaft, Werk, ...), the GND number, often VIAF. The dump has no Wikidata
numbers; they come from the local index ``compendium wikidata build`` writes out of two dewiki dumps. This counts,
for the entities the endpoint links, what its own linking (``_link``) returns - no network.

Texts: the opening of the main article of each of the 20 topics of M1 (hauptartikel.yaml, art normal), up to
2000 characters, recognised by the dictionary way of the endpoint (the spaCy model lives in the image only; a name
it finds links through the same function). Writes entity titles and identifiers, no article text.

--wikidata <db>   ask the local Wikidata index as well, and time the linking with and without it;
--gegen <json>    compare its numbers with the Wikidata links lobid-gnd names for the sampled GND records;
--lobid <n> <json> check n GND numbers, drawn with a fixed seed and every Normdaten kind present, against
                  lobid-gnd (the hbz service over the GND, one request a second): does the record name what the
                  article is about? The only step with network; it sends nothing but the numbers.

Usage (project venv, from the project root):
python docs/entwicklung/messung/mc_entitaeten_gnd.py <out.json> [--wikidata <db>] [--gegen <json>] [--lobid <n> <json>]
"""

from __future__ import annotations

import json
import os
import random
import statistics
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
from app.sources.wikidata.index import WikidataIndex

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
EVAL = Path("eval") / "artikelwahl" / "hauptartikel.yaml"
TEXT_CHARS = 2000
MAX_ENTITIES = 50  # the endpoint's default
SEED = 20260924
USER_AGENT = "kompendium-messung/1.0 (+https://github.com/janschachtschabel/compendius-textgenerator-sc26)"


def option(name: str, count: int = 1) -> list[str] | None:
    if name not in sys.argv:
        return None
    at = sys.argv.index(name)
    return sys.argv[at + 1 : at + 1 + count]


wikidata_path = option("--wikidata")
wikidata = WikidataIndex(Path(wikidata_path[0])) if wikidata_path else None
if wikidata is not None and not wikidata.available:
    raise SystemExit(f"Wikidata-Index nicht brauchbar: {wikidata.path}")
service = cli_service(ZIMS)
registry = service.registry
wiki = registry.primary_archive
assert wiki is not None
topics = [e["anfrage"] for e in yaml.safe_load(EVAL.read_text(encoding="utf-8"))["anfragen"] if e["art"] == "normal"]

rows = []
seconds: dict[str, list[float]] = {"ohne": [], "mit": []}
for topic in topics:
    main = registry.resolve_topic(topic)
    article = wiki.read(main.title) if main.title else None
    if article is None:
        continue
    text = wiki.parse(article).text[:TEXT_CHARS]
    mentions = merge(mentions_from_titles(registry.archives, text))[:MAX_ENTITIES]
    linked = [_link(registry.archives, mention) for mention in mentions]  # untimed: both timings then read warm
    for label, index in (("ohne", None), ("mit", wikidata)) if wikidata else (("ohne", None),):
        started = time.perf_counter()
        linked = [_link(registry.archives, mention, index) for mention in mentions]
        seconds[label].append(time.perf_counter() - started)
    entities = []
    for mention, found in zip(mentions, linked, strict=True):
        if found is None:  # the endpoint drops a dictionary term behind a disambiguation page
            continue
        ids = found.ids.model_dump(exclude={"dbpedia", "same_as"}) if found.ids else None
        entities.append({"text": mention.text, "titel": found.title, "projekt": found.project, "art": found.kind})
        if ids is not None:
            entities[-1]["ids"] = ids
    rows.append({"thema": topic, "hauptartikel": main.title, "begriffe": len(mentions), "entitaeten": entities})

Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
entities = [e for r in rows for e in r["entitaeten"]]
wikipedia = [e for e in entities if "ids" in e]
with_gnd = [e for e in wikipedia if e["ids"]["gnd"]]
print(
    f"Texte {len(rows)}, Begriffe {sum(r['begriffe'] for r in rows)}, verknüpft {len(entities)} "
    f"(Wikipedia {len(wikipedia)}); mit GND {len(with_gnd)}, mit Normdaten-Art "
    f"{sum(bool(e['ids']['gnd_kind']) for e in wikipedia)}, mit VIAF {sum(bool(e['ids']['viaf']) for e in wikipedia)}"
)
print("GND-Art:", dict(Counter(e["ids"]["gnd_kind"] for e in with_gnd).most_common()))
print("mit GND nach Art des Dienstes:", dict(Counter(e["art"] or "Sache" for e in with_gnd)))
if wikidata is not None:
    with_qid = [e for e in wikipedia if e["ids"]["wikidata"]]
    print(
        f"mit Wikidata {len(with_qid)} von {len(wikipedia)}; mit GND und Wikidata "
        f"{sum(bool(e['ids']['wikidata']) for e in with_gnd)}; Index: {wikidata.meta()['articles']} Artikel"
    )
    print("ohne Wikidata:", sorted({e["titel"] for e in wikipedia if not e["ids"]["wikidata"]})[:25])
for label, values in seconds.items():
    if values:
        print(f"Verknüpfen je Text {label} Wikidata: Median {statistics.median(values) * 1000:.0f} ms")

compare = option("--gegen")
if compare and wikidata is not None:
    agree = differ = missing = 0
    for row in json.loads(Path(compare[0]).read_text(encoding="utf-8")):
        lobid = [uri.rsplit("/", 1)[-1] for uri in row.get("wikidata", [])]
        ours = wikidata.qid(row["titel"])
        if not lobid or ours is None:
            missing += 1
        elif ours in lobid:
            agree += 1
        else:
            differ += 1
            print(f"  anders: {row['titel']}: Index {ours}, lobid {lobid}")
    print(f"Gegen lobid-gnd: gleich {agree}, anders {differ}, eine Seite ohne Nummer {missing}")


def sample(entities: list[dict], size: int) -> list[dict]:
    """Up to eight subject headings and six of every other kind, then random ones, all with a fixed seed."""
    rng = random.Random(SEED)  # noqa: S311 - a reproducible sample, not a secret
    unique = list({e["ids"]["gnd"]: e for e in entities}.values())
    by_kind: dict[str, list[dict]] = {}
    for entity in unique:
        by_kind.setdefault(entity["ids"]["gnd_kind"] or "", []).append(entity)
    picked = []
    for kind, group in by_kind.items():
        rng.shuffle(group)
        picked += group[: 8 if kind == "Sachbegriff" else 6]
    rest = [e for e in unique if e not in picked]
    rng.shuffle(rest)
    return (picked + rest)[:size]


lobid = option("--lobid", 2)
if lobid:
    size, sample_path = int(lobid[0]), Path(lobid[1])
    checked = []
    for entity in sample(with_gnd, size):
        gnd = entity["ids"]["gnd"]
        request = urllib.request.Request(
            f"https://lobid.org/gnd/{gnd}.json", headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - a fixed https host
            record = json.load(response)
        checked.append(
            {
                "text": entity["text"],
                "titel": entity["titel"],
                "art": entity["ids"]["gnd_kind"],
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
