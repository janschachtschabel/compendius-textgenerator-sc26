"""Latency of two b-api models side by side, on fresh prompts at the same time (M19).

The b-api answers a prompt it has seen from its cache, and its latency changes from day to day, so times from
different runs do not compare. Here both models get the same prompts in the same minutes, alternating which goes
first, and every prompt carries a random run id so nothing comes from the cache. The task has the shape of the hit
check: rate twelve article titles for a topic, answer as JSON.

Usage (project venv, from the project root): python docs/entwicklung/messung/mc_latenz_modelle.py <out.json> <model>...
"""

from __future__ import annotations

import json
import os
import secrets
import statistics
import sys
import time
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.llm.client import BApiClient
from app.settings import get_settings

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

TOPICS = [
    "Photosynthese",
    "Optik",
    "Römisches Reich",
    "Lineare Funktion",
    "Klimawandel",
    "Atommodell",
    "Sinfonie",
    "Demokratie",
]
ARTICLES = [
    "Chlorophyll",
    "Kernwaffe",
    "Linse (Optik)",
    "Probit-Modell",
    "Treibhauseffekt",
    "Augustus",
    "Orchester",
    "Gewaltenteilung",
    "Regenbogen",
    "Zellkern",
    "Differenzierbarkeit",
    "Lea Dohm",
]
SYSTEM = (
    "Du beurteilst, welche Lexikonartikel in ein Kompendium zu einem Unterrichtsthema gehören. Note 2 = gehört zum "
    "Thema, 1 = verwandt, 0 = passt nicht. Antworte nur mit einem JSON-Objekt, das jede Artikel-ID auf ihre Note "
    "abbildet."
)

out_path, models = Path(sys.argv[1]), sys.argv[2:]
if out_path.exists():  # every run keeps its own file: an overwritten run can no longer be checked (M19)
    raise SystemExit(f"{out_path} gibt es schon; jeder Lauf bekommt eine eigene Datei")
settings = get_settings()  # the key stays in the settings and is never written out
base_url = settings.b_api_url
clients = {m: BApiClient(base_url, settings.b_api_key, provider="openai", model=m, max_concurrency=1) for m in models}
calls: list[dict] = []
listing = "\n".join(f"a{number}: {title}" for number, title in enumerate(ARTICLES, 1))
for round_number, topic in enumerate(TOPICS):
    run_id = secrets.token_hex(4)
    messages = [
        {"role": "system", "content": f"{SYSTEM} (Lauf {run_id})"},
        {"role": "user", "content": f"Thema: {topic}\n\nArtikel:\n{listing}\n\nGib das JSON-Objekt zurück."},
    ]
    order = models if round_number % 2 == 0 else list(reversed(models))
    for model in order:
        client = clients[model]
        started = time.perf_counter()
        result = client.chat(messages, max_output_tokens=client.completion_limit(12 * len(ARTICLES)))
        calls.append(
            {
                "modell": model,
                "thema": topic,
                "s": round(time.perf_counter() - started, 2),
                "eingabe": result.prompt_tokens,
                "ausgabe": result.completion_tokens,
            }
        )

out_path.write_text(json.dumps(calls, ensure_ascii=False, indent=1), encoding="utf-8")
for model in models:
    mine = [c for c in calls if c["modell"] == model]
    seconds = [c["s"] for c in mine]
    print(
        f"{model:13} Median {statistics.median(seconds):.2f} s (min {min(seconds):.2f}, max {max(seconds):.2f}) | "
        f"Eingabe {statistics.median(c['eingabe'] for c in mine):.0f} | "
        f"Ausgabe Median {statistics.median(c['ausgabe'] for c in mine):.0f} Tokens"
    )
