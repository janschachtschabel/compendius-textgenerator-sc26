"""How the service finds the main article of a real material (M21): title, keywords, entities or the LLM.

Node input (D45) takes the title of a node as the topic. Real materials often name their format or source instead
("Funktionsweise eines Galvanometer - Experiment", "21./22. April 1946"), so this compares ways to find the article
a compendium should build on, on the gold eval/materialwahl/materialien.yaml, in the flow of the service:

- S0 title: the title as topic, as node input does today (derive_topic, then the rules)
- S1 title without format: the title cut at separators (" - ", " | ", ":", ";") into parts, format words stripped
  ("Lernvideo zu", "Arbeitsheft"); the first part the rules resolve with confidence, else the first they resolve
- S2 keyword: the keyword named most often in title and description, resolved by the rules
- S3 entities: the terms of title and description that have an article (the dictionary of /entities, with D46),
  linked, and ranked: in the title 3, each mention in the description 1, equal to a keyword 2
- S4 LLM: the model names the German Wikipedia article from title, subjects, keywords and description; the rules
  look the name up (redirects, variants)

Every material is read anew from its repository, anonymously as the service reads nodes; the output holds titles and
decisions only, no descriptions and no article text.

Usage (project venv, from the project root; S4 needs LLM_ENABLED and B_API_KEY in .env, the key is never printed):
python docs/entwicklung/messung/mc_material_artikelwahl.py <out.json> [--ohne-llm]
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import yaml

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.api.v2.entities import _link  # the endpoint's own linking
from app.cli_common import cli_service
from app.knowledge.recognise import mentions_from_titles, merge
from app.llm.client import BApiClient
from app.settings import get_settings
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import derive_topic, node_topic

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD = Path("eval") / "materialwahl" / "materialien.yaml"
TEXT_CHARS = 2000  # of the description, as the entities text of node input caps it far above
PROMPT_CHARS = 1500
SEPARATORS = re.compile(r"\s+[-–|]\s+|\s*[:;\]]\s+")
# Words that say what a material is, not what it is about; stripped from title parts and never an entity's winner
FORMAT_WORDS = frozenset(
    "arbeitsblatt arbeitsblätter arbeitsheft experiment versuch lernvideo erklärvideo video videos kurs online-kurs "
    "landkarte karte quiz test übung übungen stationsarbeit stationenlernen unterrichtsreihe unterrichtseinheit "
    "unterrichtsmaterial präsentation tafelbild lernpfad lückentext kreuzworträtsel suchsel simulation app "
    "interview podcast projektideen gruppenpuzzle fachportal abschlussarbeit klassenarbeit teil variante "
    "experimentiervideo lehrvideo stummes oer mint-app".split()
)
FILLERS = frozenset("zu zum zur über von vom mit im in der die das den des ein eine einer eines und".split())
SYSTEM = (
    "Du bestimmst für ein Unterrichtsmaterial das fachliche Thema, zu dem ein Kompendium für Lehrkräfte geschrieben "
    'werden soll. Antworte ausschließlich mit einem JSON-Objekt wie {"titel": "..."}: dem genauen Titel des '
    'deutschsprachigen Wikipedia-Artikels zu diesem Thema, oder "", wenn das Material kein fachliches Thema hat. '
    "Keine Erklärungen."
)


def canonical(archive: Any, titles: list[str]) -> set[str]:
    """The accepted titles as the archive names them after a redirect."""
    found = set()
    for title in titles:
        article = archive.read(title)
        found.add(article.title if article is not None else title)
    return found


def resolved(service: Any, topic: str, subjects: list[str], context: list[str]) -> tuple[str | None, bool]:
    derived = derive_topic(topic, [])
    resolution = service.registry.resolve_topic(
        derived.normalized.topic,
        context=[*derived.normalized.context, *context],
        query=derived.normalized.query,
        terms=service.subjects.context_terms_of(subjects),
    )
    return (resolution.title if resolution.resolved else None), bool(resolution.confident)


def strip_format(part: str) -> str:
    words = part.split()
    while words and (words[0].lower().strip("\"'«»") in FORMAT_WORDS | FILLERS):
        words = words[1:]
    while words and words[-1].lower().strip("\"'«»:") in FORMAT_WORDS | FILLERS:
        words = words[:-1]
    return " ".join(words).strip(" \"'«»")


def title_parts(title: str) -> list[str]:
    return [cleaned for part in SEPARATORS.split(title) if (cleaned := strip_format(part)) and len(cleaned) > 2]


def entity_ranking(service: Any, title: str, description: str, keywords: list[str]) -> list[tuple[str, float]]:
    text = f"{title}\n{description[:TEXT_CHARS]}"
    keys = {keyword.casefold() for keyword in keywords}
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    for mention in merge(mentions_from_titles(service.registry.archives, text)):
        if mention.text.casefold() in FORMAT_WORDS:
            continue
        article = _link(service.registry.archives, mention)
        if article is None:
            continue
        score = 3.0 if mention.start < len(title) else 1.0
        if mention.text.casefold() in keys or article.title.casefold() in keys:
            score += 2.0
        scores[article.title] = scores.get(article.title, 0.0) + score
        first_seen.setdefault(article.title, mention.start)
    return sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))


def ask_llm(client: BApiClient, info: Any) -> tuple[str, int]:
    user = (
        f"Titel: {info.title}\nFächer: {', '.join(info.subject_labels) or 'keine'}\n"
        f"Schlagwörter: {', '.join(info.keywords) or 'keine'}\nBeschreibung: {info.description[:PROMPT_CHARS]}\n\n"
        "Gib das JSON-Objekt zurück."
    )
    result = client.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        max_output_tokens=client.completion_limit(60),
    )
    try:
        named = str(json.loads(re.search(r"\{.*\}", result.text, re.S).group(0)).get("titel") or "")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        named = ""
    return named.strip(), result.total_tokens


out_path, with_llm = Path(sys.argv[1]), "--ohne-llm" not in sys.argv
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
if with_llm:
    os.environ["LLM_ENABLED"] = "true"
settings = get_settings()
service = cli_service(ZIMS)
wiki = service.registry.primary_archive
assert wiki is not None
llm = (
    BApiClient(
        settings.b_api_url,
        settings.b_api_key,
        provider=settings.b_api_provider,
        model=settings.b_api_model,
        max_concurrency=1,
    )
    if with_llm
    else None
)
gold = yaml.safe_load(GOLD.read_text(encoding="utf-8"))["materialien"]
readers: dict[str, EduSharingClient] = {}
rows: list[dict[str, Any]] = []
seconds: dict[str, list[float]] = {name: [] for name in ("S0", "S1", "S2", "S3", "S4")}
for entry in gold:
    reader = readers.setdefault(entry["repository"], EduSharingClient(entry["repository"], timeout_s=30))
    info = reader.node(entry["node_id"])
    subjects, found = list(info.subject_uris), node_topic(info)
    accepted = canonical(wiki, entry["akzeptiert"])
    row: dict[str, Any] = {
        "node_id": entry["node_id"],
        "titel": entry["titel"],
        "art": entry["art"],
        "akzeptiert": sorted(accepted),
    }

    started = time.perf_counter()
    title, sure = resolved(service, info.title, subjects, found.context)
    seconds["S0"].append(time.perf_counter() - started)
    row["S0"] = {"titel": title, "sicher": sure}

    started = time.perf_counter()
    choice: tuple[str | None, bool, str] = (None, False, "")
    for part in title_parts(info.title):
        title, sure = resolved(service, part, subjects, found.context)
        if title and (sure or choice[0] is None):
            choice = (title, sure, part)
            if sure:
                break
    seconds["S1"].append(time.perf_counter() - started)
    row["S1"] = {"titel": choice[0], "sicher": choice[1], "anfrage": choice[2]}

    started = time.perf_counter()
    text = f"{info.title} {info.description}".casefold()
    ranked_keywords = sorted(
        (k for k in dict.fromkeys(info.keywords) if k.casefold() not in FORMAT_WORDS),
        key=lambda k: -(3 * info.title.casefold().count(k.casefold()) + text.count(k.casefold())),
    )
    keyword_choice: tuple[str | None, str] = (None, "")
    for keyword in ranked_keywords[:5]:
        title, _ = resolved(service, keyword, subjects, found.context)
        if title:
            keyword_choice = (title, keyword)
            break
    seconds["S2"].append(time.perf_counter() - started)
    row["S2"] = {"titel": keyword_choice[0], "schlagwort": keyword_choice[1]}

    started = time.perf_counter()
    ranking = entity_ranking(service, info.title, info.description, list(info.keywords))
    seconds["S3"].append(time.perf_counter() - started)
    row["S3"] = {"titel": ranking[0][0] if ranking else None, "kandidaten": [t for t, _ in ranking[:3]]}

    if llm is not None:
        started = time.perf_counter()
        named, tokens = ask_llm(llm, info)
        title = resolved(service, named, subjects, found.context)[0] if named else None
        seconds["S4"].append(time.perf_counter() - started)
        row["S4"] = {"titel": title, "genannt": named, "tokens": tokens}

    for name in ("S0", "S1", "S2", "S3", "S4"):
        if name in row:
            row[name]["richtig"] = row[name]["titel"] in accepted
    rows.append(row)
    print(
        f"{entry['art']:8} {info.title[:44]:44} | "
        + " | ".join(
            f"{n} {'+' if row[n]['richtig'] else '-'} {str(row[n]['titel'])[:22]}"
            for n in ("S0", "S1", "S2", "S3", "S4")
            if n in row
        )
    )

# combinations, from the single ways: the rules where they are sure, else a second way
for row in rows:
    s1 = row["S1"]
    row["K1"] = {"titel": s1["titel"] if s1["sicher"] else row["S3"]["titel"]}
    if "S4" in row:
        row["K2"] = {"titel": s1["titel"] if s1["sicher"] else row["S4"]["titel"]}
    for name in ("K1", "K2"):
        if name in row:
            row[name]["richtig"] = row[name]["titel"] in set(row["akzeptiert"])

out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
judged = [row for row in rows if row["art"] != "keins"]
clear = [row for row in rows if row["art"] == "klar"]
print(
    f"\n{len(rows)} Materialien, davon {len(clear)} klar, {len(judged) - len(clear)} unscharf, {len(rows) - len(judged)} keins"
)
for name in ("S0", "S1", "S2", "S3", "S4", "K1", "K2"):
    if name not in rows[0]:
        continue
    right = sum(row[name]["richtig"] for row in judged)
    right_clear = sum(row[name]["richtig"] for row in clear)
    empty = sum(row[name]["titel"] is None for row in judged)
    none_right = sum(row[name]["titel"] is None for row in rows if row["art"] == "keins")
    timing = f", Median {statistics.median(seconds[name]) * 1000:.0f} ms" if name in seconds and seconds[name] else ""
    print(
        f"{name}: richtig {right} von {len(judged)} (klar {right_clear} von {len(clear)}), ohne Artikel {empty}, bei keins leer {none_right}{timing}"
    )
if llm is not None:
    print("S4 Tokens:", sum(row["S4"]["tokens"] for row in rows))
