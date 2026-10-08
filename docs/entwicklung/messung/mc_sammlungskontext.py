"""Messskript M71, Teil 1 (08.10.2026): Sammlungen mit inhaltsneutralem Titel und ihr Kontext im Themenbaum.

Jan: Eine Sammlung als node_id gibt ihren Titel als Thema, und mancher Titel im Themenbaum sagt nichts über den Inhalt
(„Grundlagen“); Fach, Bildungsstufe und über- oder untergeordnete Sammlungen könnten den Kontext geben - trennscharf,
ohne was eher bei anderen Sammlungen des Baums liegt. Dieses Skript sucht im WLO-Staging-Repository Sammlungen zu
Wörtern, die oft allein als Titel stehen, und hält je Sammlung fest, was ihren Kontext ausmacht: Fächer,
Bildungsstufen, Beschreibung, Schlagwörter, den Pfad der übergeordneten Sammlungen bis unter das Fachportal
(``virtual:primaryparent_nodeid``), die eigenen Untersammlungen und die Titel der ersten Materialien. Nachbarn
(die anderen Untersammlungen der Eltern) liest es nicht: sie gehören nicht zu dieser Sammlung.

Usage (aus dem Projektordner, ohne LLM): python docs/entwicklung/messung/mc_sammlungskontext.py <out.json> [<wort> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://repository.staging.openeduhub.net/edu-sharing/rest"
WORDS = [
    "Grundlagen", "Einführung", "Einstieg", "Überblick", "Basiswissen", "Grundbegriffe", "Vertiefung", "Übungen",
    "Aufgaben", "Materialien", "Arbeitsblätter", "Methoden", "Wiederholung", "Allgemeines", "Sonstiges",
    "Anfangsunterricht", "Lernpfade", "Videos", "Experimente", "Hintergrund", "Theorie", "Anwendungen",
]
MAX_PATH = 3  # ancestors below the subject portal
MAX_CHILDREN = 30
MAX_MATERIALS = 15


def get(http: httpx.Client, path: str, **params: object) -> dict:
    response = http.get(BASE + path, params=params, headers={"Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def first(props: dict, key: str) -> str:
    values = props.get(key) or []
    return str(values[0]) if values else ""


def collection(http: httpx.Client, node_id: str) -> dict:
    return get(http, f"/collection/v1/collections/-home-/{node_id}")["collection"]


def context(http: httpx.Client, node: dict) -> dict:
    props = node.get("properties") or {}
    subjects = list(props.get("ccm:taxonid_DISPLAYNAME") or [])
    path: list[str] = []
    parent = first(props, "virtual:primaryparent_nodeid")
    while parent and len(path) < MAX_PATH:
        try:
            above = collection(http, parent)
        except httpx.HTTPError:
            break
        title = above.get("title") or ""
        if not title or title in subjects or title == "WLO" or title.isdigit():
            break  # the subject portal or the root above it
        path.insert(0, title)
        parent = first(above.get("properties") or {}, "virtual:primaryparent_nodeid")
    node_id = node["ref"]["id"]
    subs = get(http, f"/collection/v1/collections/-home-/{node_id}/children/collections", maxItems=MAX_CHILDREN)
    refs = get(
        http, f"/collection/v1/collections/-home-/{node_id}/children/references",
        maxItems=MAX_MATERIALS, skipCount=0, propertyFilter="-all-",
    )
    return {
        "id": node_id,
        "title": node.get("title") or "",
        "subjects": subjects,
        "levels": list(props.get("ccm:educationalcontext_DISPLAYNAME") or []),
        "description": first(props, "cm:description")[:400],
        "keywords": list(props.get("cclom:general_keyword") or [])[:15],
        "path": path,
        "children": [c.get("title") or "" for c in subs.get("collections") or []],
        "materials": [r.get("title") or r.get("name") or "" for r in refs.get("references") or refs.get("nodes") or []],
    }


def main() -> None:
    out = Path(sys.argv[1])
    words = sys.argv[2:] or WORDS
    found: dict[str, dict] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    with httpx.Client(timeout=30.0) as http:
        for word in words:
            hits = get(http, "/collection/v1/collections/-home-/search", query=word, maxItems=60, skipCount=0)
            for node in hits.get("collections") or []:
                node_id = node["ref"]["id"]
                if node_id in found:
                    continue
                try:
                    entry = context(http, collection(http, node_id))
                except httpx.HTTPError as exc:
                    print(f"# {node_id}: {exc}", file=sys.stderr)
                    continue
                entry["word"] = word
                found[node_id] = entry
            out.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{word}: {len(found)} Sammlungen bisher", flush=True)


if __name__ == "__main__":
    main()
