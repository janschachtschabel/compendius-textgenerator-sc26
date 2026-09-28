"""M45: the four profiles at every endpoint, on the code of release 2.2.2, through the development container.

Time and tokens of each profile wherever the profiles differ: /compendium (part 1 and 2), /knowledge, /qa,
/lehrplan/search and /entities. As in M27b every LLM profile gets topics of its own that no earlier measurement
asked, because the b-api answers a repeated prompt from its cache in tenths of a second; llm-free sends no prompt and
runs on all of them, after an untimed warm pass. Tokens come from the service's own counters in /metrics
(kompendium_llm_tokens_total by route, since audit BE-04), read before and after each request, so every endpoint is
counted the same way; the requests run one after the other. The texts for /qa and /entities are part 1 of this
run's llm-free compendiums and stay in memory. Quality is not measured here: page 09 takes it from the gold and
rater measurements of each method.

Usage (project venv; the development container with the LLM switched on, see messung/README):
python docs/entwicklung/messung/mc_profile_endpunkte.py <out.json> [<base url>] [--nur-llm-free]

--nur-llm-free runs only llm-free, the same requests without any prompt: the local steps of another machine, such as
the server, at no token cost.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ONLY_FREE = "--nur-llm-free" in sys.argv
args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
out_path = Path(args[0])
BASE = (args[1] if len(args) > 1 else "http://127.0.0.1:8001").rstrip("/")
if out_path.exists():
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")

# Topics no earlier measurement file names (checked against docs/entwicklung/messung and eval on 2026-09-28)
COMPENDIUM = {
    "balanced": ["Bienen", "Gezeiten", "Seidenstraße", "Logarithmus", "Fabel", "Katalysator"],
    "best-quality": ["Hormone", "Korallenriff", "Wikinger", "Zinsrechnung", "Urheberrecht", "Kompass"],
    "best-quality-generated": ["Amphibien", "Regenwald", "Ritter", "Alphabet", "Recycling", "Transistor"],
}
KNOWLEDGE = {"balanced": ["Dinosaurier", "Tsunami", "Burg"], "best-quality": ["Savanne", "Münze", "Impfung"]}
QUERIES = ["Pilze", "Insekten", "Kläranlage", "Trinkwasser", "Lautsprecher", "Glas"]
PARTS = ["world", "curricula"]
ENTITY_CHARS = 1500  # about the length of a material's description, the texts of M36
QA_PAIRS = 20  # as M30 and M34

client = httpx.Client(base_url=BASE, timeout=900)
_METRIC = re.compile(r'^kompendium_llm_(tokens|calls)_total\{endpoint="([^"]+)",(?:type|outcome)="([^"]+)"\} ([0-9.e+]+)$')


def counters() -> dict[tuple[str, str, str], float]:
    found: dict[tuple[str, str, str], float] = {}
    for line in client.get("/metrics").text.splitlines():
        match = _METRIC.match(line)
        if match:
            found[(match.group(1), match.group(2), match.group(3))] = float(match.group(4))
    return found


def usage(before: dict[tuple[str, str, str], float], after: dict[tuple[str, str, str], float], route: str) -> dict[str, int]:
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


def call(method: str, path: str, route: str, **kwargs: Any) -> tuple[int, dict[str, Any], float, dict[str, int]]:
    before = counters()
    started = time.perf_counter()
    response = client.request(method, path, **kwargs)
    seconds = time.perf_counter() - started
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    return response.status_code, body, round(seconds, 2), usage(before, counters(), route)


def part1_text(body: dict[str, Any]) -> str:
    """The prose of part 1 without citation markers, as a caller would send it on."""
    text = "\n\n".join(str(section.get("text") or "") for section in body.get("sections") or [])
    return re.sub(r"\s*\[\d+\]", "", text).strip()


def compendium(topic: str, profile: str) -> tuple[dict[str, Any], str]:
    status, body, seconds, used = call(
        "POST", "/api/v2/compendium", "/api/v2/compendium", json={"topic": topic, "preset": profile, "parts": PARTS}
    )
    audit = body.get("audit") or {}
    llm = audit.get("llm") or {}
    row = {
        "status": status,
        "profil": audit.get("preset"),
        "sekunden": seconds,
        **used,
        "tokens_audit": (audit.get("llm_tokens") or {}).get("total", 0),
        "phasen_ms": audit.get("timings_ms"),
        "hauptartikel": (body.get("resolution") or {}).get("title"),
        "bausteine_gefuellt": audit.get("sections_filled"),
        "absaetze_gesamt": audit.get("chunks_total"),
        "absaetze_zugeordnet": audit.get("chunks_assigned"),
        "lehrplanelemente": len((body.get("curricula") or {}).get("entries") or []),
        "teile": body.get("parts_status"),
        "llm_schritte": {key: (value or {}).get("used") for key, value in llm.items() if isinstance(value, dict)},
        "llm_hinweis": llm.get("note"),
        "zeichen_teil1": sum(len(str(section.get("text") or "")) for section in body.get("sections") or []),
    }
    return row, part1_text(body)


def summarize(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    ok = [row for row in rows if row.get("status") == 200]
    summary: dict[str, Any] = {"anfragen": len(rows), "ok": len(ok)}
    for field in fields:
        values = [row[field] for row in ok if isinstance(row.get(field), (int, float))]
        if values:
            summary[field] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
    return summary


health = client.get("/health").json()
llm_state = health["components"]["llm"]
if not ONLY_FREE and not llm_state.get("available"):
    raise SystemExit(f"LLM nicht verfügbar: {llm_state}")
stand = {
    "version": health.get("version"),
    "revision": health.get("revision"),
    "modell": llm_state.get("model"),
    "matching": health["components"]["matching"],
    "entities": {key: (value.get("available") if isinstance(value, dict) else value)
                 for key, value in health["components"]["entities"].items()},
}
print("Stand:", json.dumps(stand, ensure_ascii=False), flush=True)
result: dict[str, Any] = {
    "messung": "M45, 28.09.2026: die vier Profile an allen Endpunkten, Release 2.2.2, Entwicklungscontainer über HTTP",
    "stand": stand,
    "themen": {"compendium": COMPENDIUM, "knowledge": KNOWLEDGE, "lehrplan": QUERIES},
}

# --- /compendium: warm pass, llm-free on all topics, then the LLM profiles in turns, each on topics of its own ---
all_topics = [topic for topics in COMPENDIUM.values() for topic in topics]
for topic in all_topics:
    compendium(topic, "llm-free")
runs: dict[str, dict[str, Any]] = {"llm-free": {}}
texts: dict[str, str] = {}
for topic in all_topics:
    row, text = compendium(topic, "llm-free")
    runs["llm-free"][topic] = row
    texts[topic] = text
print("compendium llm-free fertig", flush=True)
for index in range(0 if ONLY_FREE else 6):
    for profile, topics in COMPENDIUM.items():
        topic = topics[index]
        row, _ = compendium(topic, profile)
        runs.setdefault(profile, {})[topic] = row
        print(f"compendium {topic:14} {profile:23} {row['status']} {row['sekunden']:6.1f} s {row['tokens']:6} Tok "
              f"{row['hauptartikel']} {row['llm_hinweis'] or ''}", flush=True)
result["compendium"] = {
    "laeufe": runs,
    "zusammenfassung": {
        profile: summarize(list(rows.values()), ("sekunden", "tokens", "absaetze_gesamt", "bausteine_gefuellt"))
        for profile, rows in runs.items()
    },
    "llm_free_je_satz": {} if ONLY_FREE else {
        profile: statistics.median(runs["llm-free"][topic]["sekunden"] for topic in topics)
        for profile, topics in COMPENDIUM.items()
    },
}

# --- /knowledge: the article choice of the profile, nothing else ---
knowledge_topics = [topic for topics in KNOWLEDGE.values() for topic in topics]


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
        "artikelwahl": {key: choice.get(key) for key in ("used", "asked", "method") if key in choice},
    }


for topic in knowledge_topics:
    knowledge(topic, "llm-free")
kruns: dict[str, dict[str, Any]] = {"llm-free": {topic: knowledge(topic, "llm-free") for topic in knowledge_topics}}
for index in range(0 if ONLY_FREE else 3):
    for profile, topics in KNOWLEDGE.items():
        kruns.setdefault(profile, {})[topics[index]] = knowledge(topics[index], profile)
result["knowledge"] = {
    "laeufe": kruns,
    "zusammenfassung": {p: summarize(list(r.values()), ("sekunden", "tokens", "artikel")) for p, r in kruns.items()},
}
print("knowledge:", json.dumps(result["knowledge"]["zusammenfassung"], ensure_ascii=False), flush=True)

# --- /lehrplan/search: the rules, and in best-quality the LLM grading every element found ---


def search(query: str, profile: str) -> dict[str, Any]:
    status, body, seconds, used = call(
        "GET", "/api/v2/lehrplan/search", "/api/v2/lehrplan/search", params={"q": query, "preset": profile}
    )
    return {
        "status": status,
        "sekunden": seconds,
        **used,
        "tokens_antwort": body.get("llm_tokens"),
        "treffer": len(body.get("matches") or []),
        "llm": {key: value for key, value in (body.get("llm") or {}).items() if not isinstance(value, (list, dict))},
    }


for query in QUERIES:
    search(query, "llm-free")
sruns = {
    "llm-free": {query: search(query, "llm-free") for query in QUERIES},
    **({} if ONLY_FREE else {"best-quality": {query: search(query, "best-quality") for query in QUERIES}}),
}
result["lehrplan_suche"] = {
    "laeufe": sruns,
    "zusammenfassung": {p: summarize(list(r.values()), ("sekunden", "tokens", "treffer")) for p, r in sruns.items()},
}
print("lehrplan:", json.dumps(result["lehrplan_suche"]["zusammenfassung"], ensure_ascii=False), flush=True)

# --- /qa and /entities on part 1 of the llm-free compendiums of the balanced set ---
sample = COMPENDIUM["balanced"]


def qa(text: str, profile: str) -> dict[str, Any]:
    status, body, seconds, used = call(
        "POST", "/api/v2/qa", "/api/v2/qa", json={"text": text, "preset": profile, "count": QA_PAIRS}
    )
    return {"status": status, "sekunden": seconds, **used, "verfahren": body.get("method"),
            "paare": len(body.get("pairs") or []), "zeichen": len(text)}


def entities(text: str, profile: str) -> dict[str, Any]:
    status, body, seconds, used = call(
        "POST", "/api/v2/entities", "/api/v2/entities", json={"text": text, "preset": profile}
    )
    found = body.get("entities") or []
    return {
        "status": status,
        "sekunden": seconds,
        **used,
        "tokens_antwort": (body.get("llm") or {}).get("total_tokens"),
        "wege": body.get("methods"),
        "entitaeten": len(found),
        "mit_wikidata": sum(1 for e in found if ((e.get("article") or {}).get("ids") or {}).get("wikidata")),
        "mit_gnd": sum(1 for e in found if ((e.get("article") or {}).get("ids") or {}).get("gnd")),
        "zeichen": len(text),
    }


qa(texts[sample[0]], "llm-free")  # warm the parser
qruns = {
    "llm-free": {topic: qa(texts[topic], "llm-free") for topic in sample},
    **({} if ONLY_FREE else {"best-quality": {topic: qa(texts[topic], "best-quality") for topic in sample}}),
}
result["qa"] = {
    "laeufe": qruns,
    "zusammenfassung": {p: summarize(list(r.values()), ("sekunden", "tokens", "paare", "zeichen")) for p, r in qruns.items()},
}
print("qa:", json.dumps(result["qa"]["zusammenfassung"], ensure_ascii=False), flush=True)

entities(texts[sample[0]][:ENTITY_CHARS], "llm-free")  # warm the model
eruns = {
    "llm-free": {topic: entities(texts[topic][:ENTITY_CHARS], "llm-free") for topic in sample},
    **({} if ONLY_FREE else {"balanced": {topic: entities(texts[topic][:ENTITY_CHARS], "balanced") for topic in sample}}),
}
result["entities"] = {
    "laeufe": eruns,
    "zusammenfassung": {
        p: summarize(list(r.values()), ("sekunden", "tokens", "entitaeten", "mit_wikidata", "mit_gnd"))
        for p, r in eruns.items()
    },
}
print("entities:", json.dumps(result["entities"]["zusammenfassung"], ensure_ascii=False), flush=True)

for profile, summary in result["compendium"]["zusammenfassung"].items():
    print("compendium", profile, json.dumps(summary, ensure_ascii=False), flush=True)
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"Ergebnis: {out_path}")
