"""Messskript M68 (04.10.2026): der Filter gegen Cookie-Hinweise in Materialtexten, an echten Texten des Repositorys.

Audit 2026-10-03, F08: ``paragraphs_from_text`` (app/sources/wlo/knowledge.py) verwirft jede Zeile, in der „cookie“
oder „consent“ vorkommt - auch „Cookies sind kleine Textdateien …“, und bei einem Text ohne Zeilenumbruch den ganzen
Text. Welche Zeilen der Filter in echten Materialtexten trifft, zeigt nur das Repository selbst: Materialien der
öffentlichen Suche des WLO-Staging-Repositorys zu Suchwörtern, ihre Texte (``textContent``) ohne Anmeldung gelesen.

Usage (aus dem Projektordner, ohne LLM): python docs/entwicklung/messung/mc_cookie_filter.py <texte.json> [<wort>=<anzahl> ...]

Schreibt je Material Titel, Suchwort und Text nach <texte.json> (außerhalb des Repositorys); ein Material, das dort
schon steht, wird nicht noch einmal gelesen. Die Auswertung (Zeilen je Filter) macht mc_cookie_filter_auswertung.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from app.sources.wlo.client import EduSharingClient, EduSharingError

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://repository.staging.openeduhub.net/edu-sharing/rest"
SEARCH = "/search/v1/queries/-home-/mds_oeh/ngsearch"
DEFAULT_WORDS = {"Cookies": 80, "Datenschutz": 60, "Medienkompetenz": 40, "Optik": 40, "Photosynthese": 40}


def search(http: httpx.Client, word: str, count: int) -> list[tuple[str, str]]:
    """Node id and title of the first ``count`` materials the full-text search finds for ``word``."""
    found: list[tuple[str, str]] = []
    skip = 0
    while len(found) < count:
        response = http.post(
            BASE + SEARCH,
            params={"contentType": "FILES", "maxItems": 50, "skipCount": skip, "propertyFilter": "-all-"},
            json={"criteria": [{"property": "ngsearchword", "values": [word]}], "facets": []},
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        nodes = response.json().get("nodes") or []
        if not nodes:
            break
        found += [(node["ref"]["id"], node.get("title") or node.get("name") or "") for node in nodes]
        skip += len(nodes)
    return found[:count]


def main() -> None:
    out = Path(sys.argv[1])
    words = dict((w.split("=")[0], int(w.split("=")[1])) for w in sys.argv[2:]) or DEFAULT_WORDS
    texts = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    client = EduSharingClient(BASE, timeout_s=30.0)
    with httpx.Client(timeout=30.0) as http:
        for word, count in words.items():
            for node_id, title in search(http, word, count):
                if node_id in texts:
                    continue
                try:
                    text = client.text_content(node_id)
                except EduSharingError as exc:
                    text = ""
                    print(f"# {node_id}: {exc}", file=sys.stderr)
                texts[node_id] = {"word": word, "title": title, "text": text}
            out.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
            with_text = sum(1 for t in texts.values() if t["word"] == word and t["text"])
            print(f"{word}: {with_text} Materialien mit Text", flush=True)
    client.close()


if __name__ == "__main__":
    main()
