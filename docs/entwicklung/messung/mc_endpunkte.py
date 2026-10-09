"""M82 (09.10.2026): time and tokens of every endpoint in the profiles, release 2.17.0, in the one-off container.

The requests of M45 (mc_profile_endpunkte.py, release 2.2.2) on its topics, now in every profile wherever the profiles
differ, through the app in this process with the LLM over OpenAI direct (mc_openai_direkt.py); since the b-api is out
of the way, no profile needs topics of its own (M45 gave each its own to dodge the b-api's cache). Each block runs an
untimed warm pass in llm-free first. Tokens come from the service's own counters in /metrics by route, read before and
after each request, as in M45; the requests run one after the other. Quality is not measured here.

- /knowledge: llm-free (rules), balanced (llm), best-quality (llm-thorough; best-quality-generated and
  best-coverage-generated choose the same way) on the six topics of M45;
- /lehrplan/search: the six queries of M45 as words (mode keyword: llm-free; best-quality checks every element) and
  as topics (mode topic: llm-free, balanced with the question N, best-quality with the check);
- /qa: the text of part 1 of the llm-free compendium of six topics (20 pairs, as M45) and the topic itself, llm-free
  (rules) and best-quality (llm);
- /entities: the first 1,500 characters of the same texts, llm-free, balanced (llm) and balanced with link_check llm;
- /compendium from a material (node_id, part 1): three materials of eval/materialwahl, llm-free and balanced.

  cat mc_openai_direkt.py mc_endpunkte.py | docker compose run --rm --no-deps -T -v <ordner>:/out \\
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY api \\
      python - /out/m82_endpunkte.json
"""

import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

install()  # noqa: F821 - from mc_openai_direkt.py, piped in before this file

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

out_path = Path(sys.argv[1])
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")

# The topics and queries of M45, so both measurements ask the same
TEXT_TOPICS = ["Bienen", "Gezeiten", "Seidenstraße", "Logarithmus", "Fabel", "Katalysator"]
KNOWLEDGE = ["Dinosaurier", "Tsunami", "Burg", "Savanne", "Münze", "Impfung"]
QUERIES = ["Pilze", "Insekten", "Kläranlage", "Trinkwasser", "Lautsprecher", "Glas"]
MATERIALS = [  # the first three of eval/materialwahl/materialien.yaml with a clear topic (art: klar)
    "19e322f0-afa5-440f-8dc0-fca1dcde71d8",  # Zahnrad und Riemen - Experiment
    "8e4ee58d-c18c-470b-8f84-c3a634a041c3",  # Bestimmung des Planckschen Wirkungsquantums h
    "c6c569d7-87c3-40d6-be6f-d92ee5409782",  # Funktionsweise eines Galvanometer - Experiment
]
REPOSITORY = "https://redaktion.openeduhub.net/edu-sharing/rest"
ENTITY_CHARS = 1500  # about the length of a material's description, the texts of M36
QA_PAIRS = 20  # as M30, M34 and M45
_METRIC = re.compile(r'^kompendium_llm_(tokens|calls)_total\{endpoint="([^"]+)",(?:type|outcome)="([^"]+)"\} ([0-9.e+]+)$')

client = TestClient(create_app())
client.__enter__()  # the lifespan: archives, indexes and models


def counters() -> dict[tuple[str, str, str], float]:
    found: dict[tuple[str, str, str], float] = {}
    for line in client.get("/metrics").text.splitlines():
        match = _METRIC.match(line)
        if match:
            found[(match.group(1), match.group(2), match.group(3))] = float(match.group(4))
    return found


def usage(before: dict[tuple[str, str, str], float], after: dict[tuple[str, str, str], float], route: str) -> dict[str, Any]:
    def delta(kind: str, label: str) -> int:
        key = (kind, route, label)
        return round(after.get(key, 0.0) - before.get(key, 0.0))

    calls = {
        outcome: delta("calls", outcome)
        for outcome in {key[2] for key in after if key[0] == "calls" and key[1] == route}
        if delta("calls", outcome)
    }
    prompt, completion = delta("tokens", "prompt"), delta("tokens", "completion")
    return {"tokens": prompt + completion, "prompt": prompt, "completion": completion, "aufrufe": calls}


def call(method: str, path: str, route: str, **kwargs: Any) -> tuple[int, dict[str, Any], float, dict[str, Any]]:
    before = counters()
    started = time.perf_counter()
    response = client.request(method, path, **kwargs)
    seconds = time.perf_counter() - started
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    return response.status_code, body, round(seconds, 2), usage(before, counters(), route)


def summarize(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    ok = [row for row in rows if row.get("status") == 200]
    summary: dict[str, Any] = {"anfragen": len(rows), "ok": len(ok)}
    for field in fields:
        values = [row[field] for row in ok if isinstance(row.get(field), (int, float))]
        if values:
            summary[field] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
    return summary


def part1_text(body: dict[str, Any]) -> str:
    """The prose of part 1 without citation markers, as a caller would send it on."""
    text = "\n\n".join(str(section.get("text") or "") for section in body.get("sections") or [])
    return re.sub(r"\s*\[\d+\]", "", text).strip()


def compendium(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    status, body, seconds, used = call("POST", "/api/v2/compendium", "/api/v2/compendium", json=payload)
    audit = body.get("audit") or {}
    llm = audit.get("llm") or {}
    row = {
        "status": status,
        "profil": audit.get("preset"),
        "sekunden": seconds,
        **used,
        "phasen_ms": audit.get("timings_ms"),
        "hauptartikel": (body.get("resolution") or {}).get("title"),
        "ueberschrift": body.get("topic"),
        "llm_schritte": {key: (value or {}).get("used") for key, value in llm.items() if isinstance(value, dict)},
        "llm_hinweis": llm.get("note"),
        "zeichen_teil1": sum(len(str(section.get("text") or "")) for section in body.get("sections") or []),
    }
    return row, body


def knowledge(topic: str, profile: str) -> dict[str, Any]:
    status, body, seconds, used = call(
        "POST", "/api/v2/knowledge", "/api/v2/knowledge", json={"topic": topic, "preset": profile}
    )
    choice = body.get("article_choice") or {}
    return {
        "status": status,
        "sekunden": seconds,
        **used,
        "artikel": len(body.get("articles") or []),
        "zeichen": body.get("chars"),
        "artikelwahl": {key: choice.get(key) for key in ("used", "asked", "articles_asked", "hits_checked")},
    }


def search(query: str, profile: str, mode: str) -> dict[str, Any]:
    status, body, seconds, used = call(
        "GET",
        "/api/v2/lehrplan/search",
        "/api/v2/lehrplan/search",
        params={"q": query, "preset": profile, "mode": mode, "limit": 500},
    )
    check = (body.get("llm") or {}).get("curriculum_check") or {}
    return {
        "status": status,
        "sekunden": seconds,
        **used,
        "thema": body.get("topic"),
        "treffer_gesamt": body.get("total_hits"),
        "treffer": len(body.get("matches") or []),
        "pruefung": {key: check.get(key) for key in ("used", "rated", "answered", "dropped", "fallbacks")},
    }


def qa(payload: dict[str, Any], profile: str) -> dict[str, Any]:
    status, body, seconds, used = call(
        "POST", "/api/v2/qa", "/api/v2/qa", json={**payload, "preset": profile, "count": QA_PAIRS}
    )
    return {"status": status, "sekunden": seconds, **used, "verfahren": body.get("method"),
            "paare": len(body.get("pairs") or []), "zeichen": body.get("chars"), "hinweis": body.get("note")}


def entities(text: str, profile: str, check: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": text, "preset": profile}
    if check:
        payload["link_check"] = "llm"
    status, body, seconds, used = call("POST", "/api/v2/entities", "/api/v2/entities", json=payload)
    found = body.get("entities") or []
    llm = body.get("llm") or {}
    return {
        "status": status,
        "sekunden": seconds,
        **used,
        "wege": body.get("methods"),
        "entitaeten": len(found),
        "verknuepft": sum(1 for e in found if e.get("linked")),
        "mit_wikidata": sum(1 for e in found if ((e.get("article") or {}).get("ids") or {}).get("wikidata")),
        "mit_gnd": sum(1 for e in found if ((e.get("article") or {}).get("ids") or {}).get("gnd")),
        "gestrichen": len(llm.get("dropped") or []),
        "rueckfall": llm.get("fallback"),
        "zeichen": len(text),
    }


def runs_of(name: str, rows: dict[str, dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    summary = {variant: summarize(list(by_topic.values()), fields) for variant, by_topic in rows.items()}
    print(name, json.dumps(summary, ensure_ascii=False), flush=True)
    return {"laeufe": rows, "zusammenfassung": summary}


health = client.get("/health").json()
llm_state = health["components"]["llm"]
if not llm_state.get("available"):
    raise SystemExit(f"LLM nicht verfügbar: {llm_state}")
result: dict[str, Any] = {
    "messung": "M82, 09.10.2026: alle Endpunkte je Profil, Release 2.17.0, Einmal-Container, OpenAI direkt",
    "stand": {"version": health.get("version"), "revision": health.get("revision"), "modell": llm_state.get("model")},
    "themen": {"texte": TEXT_TOPICS, "knowledge": KNOWLEDGE, "lehrplan": QUERIES, "materialien": MATERIALS},
}
print("Stand:", json.dumps(result["stand"], ensure_ascii=False), flush=True)

# --- the texts: part 1 of the llm-free compendiums, after a warm pass ---
texts: dict[str, str] = {}
for topic in TEXT_TOPICS:
    compendium({"topic": topic, "preset": "llm-free", "parts": ["world"]})
free_rows: dict[str, Any] = {}
for topic in TEXT_TOPICS:
    row, body = compendium({"topic": topic, "preset": "llm-free", "parts": ["world"]})
    free_rows[topic] = row
    texts[topic] = part1_text(body)
result["texte"] = runs_of("texte", {"llm-free": free_rows}, ("sekunden", "zeichen_teil1"))

# --- /knowledge ---
for topic in KNOWLEDGE:
    knowledge(topic, "llm-free")
result["knowledge"] = runs_of(
    "knowledge",
    {profile: {topic: knowledge(topic, profile) for topic in KNOWLEDGE} for profile in ("llm-free", "balanced", "best-quality")},
    ("sekunden", "tokens", "artikel"),
)

# --- /lehrplan/search, by words and as a topic ---
for query in QUERIES:
    search(query, "llm-free", "keyword")
    search(query, "llm-free", "topic")
search_rows: dict[str, dict[str, Any]] = {}
for variant, profile, mode in (
    ("keyword llm-free", "llm-free", "keyword"),
    ("keyword best-quality", "best-quality", "keyword"),
    ("topic llm-free", "llm-free", "topic"),
    ("topic balanced", "balanced", "topic"),
    ("topic best-quality", "best-quality", "topic"),
):
    search_rows[variant] = {query: search(query, profile, mode) for query in QUERIES}
result["lehrplan_suche"] = runs_of("lehrplan", search_rows, ("sekunden", "tokens", "treffer"))

# --- /qa from the text and from the topic ---
qa({"text": texts[TEXT_TOPICS[0]]}, "llm-free")  # warm the parser
qa_rows: dict[str, dict[str, Any]] = {}
for profile in ("llm-free", "best-quality"):
    qa_rows[f"text {profile}"] = {topic: qa({"text": texts[topic]}, profile) for topic in TEXT_TOPICS}
    qa_rows[f"topic {profile}"] = {topic: qa({"topic": topic}, profile) for topic in TEXT_TOPICS}
result["qa"] = runs_of("qa", qa_rows, ("sekunden", "tokens", "paare", "zeichen"))

# --- /entities ---
entities(texts[TEXT_TOPICS[0]][:ENTITY_CHARS], "llm-free")  # warm the model
entity_rows: dict[str, dict[str, Any]] = {
    "llm-free": {t: entities(texts[t][:ENTITY_CHARS], "llm-free") for t in TEXT_TOPICS},
    "balanced": {t: entities(texts[t][:ENTITY_CHARS], "balanced") for t in TEXT_TOPICS},
    "balanced link_check": {t: entities(texts[t][:ENTITY_CHARS], "balanced", check=True) for t in TEXT_TOPICS},
}
result["entities"] = runs_of(
    "entities", entity_rows, ("sekunden", "tokens", "entitaeten", "verknuepft", "mit_wikidata", "mit_gnd")
)

# --- a compendium from a material ---
material_rows: dict[str, dict[str, Any]] = {}
for node in MATERIALS:
    compendium({"node_id": node, "repository": REPOSITORY, "preset": "llm-free", "parts": ["world"]})
for profile in ("llm-free", "balanced"):
    material_rows[profile] = {
        node: compendium({"node_id": node, "repository": REPOSITORY, "preset": profile, "parts": ["world"]})[0]
        for node in MATERIALS
    }
result["material"] = runs_of("material", material_rows, ("sekunden", "tokens", "zeichen_teil1"))

client.__exit__(None, None, None)
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"Ergebnis: {out_path}")
