"""M36: the ways of /api/v2/entities, each as the service runs it, on the texts of 40 real WLO materials.

Jan, 2026-09-26: look at the entities endpoint and its profiles - evaluate the methods, assign fitting profiles. The
endpoint has two ways, both without an LLM: ``ner`` (the spaCy model of the image) and ``dictionary`` (terms that are
an article title), each linked to its article by title. Two LLM ways join them here as prototypes:

- extract: the LLM names the entities and subject terms of the text with the exact title of their article; a title
  counts when the archive has it as an article (redirects followed, disambiguation pages not);
- check: the LLM grades every link the other ways made - 2 an entity or term the text is about and the article
  means it, 1 fitting but minor or an everyday word, 0 the article means something else - in one call per text.

The rules run through the endpoint of the development container (the spaCy model is only in the image; the container
reads the same archives), with the text a node would give it: title, description and keywords, one per line. The LLM
ways run here against the staging b-api. The texts come from the repository at run time and stay out of this output:
it holds the titles of the articles and what each way did with them. Every article any way linked is graded blind by
two raters (eval/entitaeten/), as the pooled grades of M23: recall counts against what all ways found together.

Usage (from the project folder): python mc_entitaeten.py <out.json> <sheet.json> [<api base>]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.knowledge.article_choice import read_object  # noqa: E402
from app.llm.client import LlmError  # noqa: E402
from app.sources.wlo.client import EduSharingClient, EduSharingError  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD = Path("eval") / "materialwahl" / "materialien.yaml"
MAX_TEXT_CHARS = 50_000  # as the endpoint
LEAD_CHARS = 180  # what the check sees of an article, as the hit check of the article choice
EXTRACT_SYSTEM = (
    "Du erkennst in deutschen Texten über Unterrichtsmaterial die Entitäten, die einen Artikel in der "
    "deutschsprachigen Wikipedia haben. Antworte nur mit JSON."
)
EXTRACT_QUESTION = (
    "Text:\n{text}\n\n"
    "Nenne die Entitäten dieses Textes: Personen, Orte, Organisationen, Werke, Ereignisse und die Fachbegriffe, um "
    "die es im Text geht - keine Allerweltswörter wie Schule, Unterricht, Arbeitsblatt, Video oder Aufgabe. Je "
    "Entität das Wort, wie es im Text steht, und den genauen Titel ihres Artikels in der deutschsprachigen "
    "Wikipedia.\n"
    'Antworte so: {{"entitaeten": [{{"text": "<Wort im Text>", "titel": "<Artikeltitel>"}}]}}'
)
CHECK_SYSTEM = (
    "Du prüfst Verknüpfungen zwischen Wörtern eines Textes und Artikeln der deutschsprachigen Wikipedia. Antworte "
    "nur mit JSON."
)
CHECK_QUESTION = (
    "Text:\n{text}\n\n"
    "Zu Wörtern dieses Textes steht der Artikel, mit dem sie verknüpft wurden, und der Anfang seiner Einleitung:\n"
    "{lines}\n\n"
    "Bewerte jede Verknüpfung: 2 = eine Entität oder ein Fachbegriff, um den es im Text geht, und der Artikel meint "
    "genau das; 1 = der Artikel passt, aber das Wort ist nebensächlich oder ein Allerweltswort; 0 = der Artikel meint "
    "etwas anderes als der Text.\n"
    'Antworte so: {{"a1": 2, "a2": 0}}'
)

out_path, sheet_path = Path(sys.argv[1]), Path(sys.argv[2])
api = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8001"
service = cli_service(ZIMS)
assert service.llm is not None, "LLM_ENABLED did not reach the settings"
client = service.llm.client
wiki = service.registry.primary_archive
assert wiki is not None
http = httpx.Client(base_url=api, timeout=120)


def node_text(info: Any) -> str:
    """What the endpoint reads from a node (entities._node_text)."""
    lines = [info.title, info.description, ", ".join(info.keywords)]
    return "\n".join(line for line in lines if line)[:MAX_TEXT_CHARS]


def by_rules(text: str, methods: list[str]) -> tuple[list[dict[str, str]], float]:
    """The linked entities of the endpoint for these methods, at its defaults otherwise."""
    started = time.perf_counter()
    answer = http.post("/api/v2/entities", json={"text": text, "methods": methods})
    answer.raise_for_status()
    seconds = round(time.perf_counter() - started, 3)
    found = [
        {"text": e["text"], "titel": e["article"]["title"], "quelle": e["source"]}
        for e in answer.json()["entities"]
        if e["linked"] and e["article"]["project"] == "wikipedia"
    ]
    return found, seconds


def article(title: str) -> tuple[str, str] | None:
    """The article of a title the model named, with the beginning of its lead; ``None`` without one."""
    found = wiki.read_article(title) if title else None
    if found is None:
        return None
    parsed = wiki.parse(found)
    if parsed.is_disambiguation:
        return None
    return parsed.title, " ".join(parsed.text.split())[:400]


def ask(system: str, question: str, limit: int) -> tuple[dict[str, Any], int, float]:
    started = time.perf_counter()
    result = client.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": question}],
        max_output_tokens=client.completion_limit(limit),
    )
    return read_object(result.text) or {}, result.total_tokens, round(time.perf_counter() - started, 2)


rows: list[dict[str, Any]] = []
sheets: list[dict[str, Any]] = []
for entry in yaml.safe_load(GOLD.read_text(encoding="utf-8"))["materialien"]:
    try:
        info = EduSharingClient(entry["repository"], timeout_s=30).node(entry["node_id"])
    except EduSharingError as exc:
        print(f"{entry['node_id']}: {str(exc)[:100]}")
        rows.append({"node_id": entry["node_id"], "status": "nicht lesbar"})
        continue
    text = node_text(info)
    leads: dict[str, str] = {}
    ways: dict[str, Any] = {}
    for way, methods in (("ner", ["ner"]), ("dictionary", ["dictionary"]), ("regeln", ["ner", "dictionary"])):
        found, seconds = by_rules(text, methods)
        ways[way] = {"artikel": list(dict.fromkeys(f["titel"] for f in found)), "sekunden": seconds,
                     "erwaehnungen": [[f["text"], f["titel"], f["quelle"]] for f in found]}  # fmt: skip

    try:
        answer, tokens, seconds = ask(EXTRACT_SYSTEM, EXTRACT_QUESTION.format(text=text), 1200)
    except LlmError as exc:
        answer, tokens, seconds = {}, 0, 0.0
        print(f"   extract: {str(exc)[:120]}")
    named = [item for item in answer.get("entitaeten") or [] if isinstance(item, dict)]
    extracted: list[str] = []
    for item in named:
        hit = article(str(item.get("titel") or "").strip())
        if hit is not None and hit[0] not in extracted:
            extracted.append(hit[0])
            leads.setdefault(hit[0], hit[1])
    ways["extract"] = {"artikel": extracted, "genannt": [[str(i.get("text")), str(i.get("titel"))] for i in named],
                       "tokens": tokens, "sekunden": seconds}  # fmt: skip

    # the combined run is its own way: with both methods the cap of max_entities keeps other mentions than either alone
    rules = [*ways["ner"]["artikel"], *ways["dictionary"]["artikel"], *ways["regeln"]["artikel"]]
    pool = list(dict.fromkeys([*rules, *extracted]))
    for title in pool:
        if title not in leads:
            hit = article(title)
            leads[title] = hit[1] if hit is not None else ""
    mention = {t: m for m, t, _ in ways["regeln"]["erwaehnungen"][::-1]}
    mention.update({str(t): str(m) for m, t in ways["extract"]["genannt"]})
    aliases = {f"a{i}": title for i, title in enumerate(pool, 1)}
    lines = "\n".join(
        f"{alias}: „{mention.get(title, title)}“ → {title}: {leads[title][:LEAD_CHARS]}"
        for alias, title in aliases.items()
    )
    notes: dict[str, int] = {}
    tokens = 0
    seconds = 0.0
    if pool:
        try:
            answer, tokens, seconds = ask(
                CHECK_SYSTEM, CHECK_QUESTION.format(text=text, lines=lines), 20 * len(pool) + 200
            )
        except LlmError as exc:
            answer = {}
            print(f"   check: {str(exc)[:120]}")
        for alias, title in aliases.items():
            note = answer.get(alias)
            if isinstance(note, int) and note in (0, 1, 2):
                notes[title] = note
    ways["pruefung"] = {"noten": notes, "tokens": tokens, "sekunden": seconds, "gefragt": len(pool)}

    rows.append(
        {"node_id": entry["node_id"], "titel": entry["titel"], "zeichen": len(text), "pool": pool, "wege": ways}
    )
    sheets.append({"node_id": entry["node_id"], "text": text, "artikel": {t: leads[t] for t in pool}})
    print(
        f"{entry['titel'][:40]:40s} ner {len(ways['ner']['artikel']):2d}  "
        f"dict {len(ways['dictionary']['artikel']):2d}  extract {len(extracted):2d}  pool {len(pool):2d}  "
        f"geprüft {len(notes):2d}",
        flush=True,
    )

out_path.write_text(json.dumps({"materialien": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
sheet_path.write_text(json.dumps(sheets, ensure_ascii=False, indent=1), encoding="utf-8")
