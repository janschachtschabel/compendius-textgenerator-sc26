"""Part 1 of the new service for the ten gold topics: timing on the server, citations checked sentence by sentence.

The server answers with the language model switched off (rule-based). Locally the same topic is prepared from the
same archives, so the paragraph behind every evidence number is known: each sentence of the matched blocks (1-5,
7-11) must occur word for word in the paragraph its own number cites. List items carry no number of their own (the
list as a whole is cited); they are looked up in the paragraphs their block cites. Sentences are split with the
service's own citation code, as for the old service (old_analyze.py).

Usage (project venv): python new_part1_check.py <base-url> <out.json>
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from app.cli_common import cli_service
from app.domain.requests import GenerateRequest
from app.synthesis.citations import _cited_sentences, _units

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE, OUT = sys.argv[1].rstrip("/"), Path(sys.argv[2])
DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
TOPICS = [
    "Barockliteratur", "Bruchrechnung", "Demokratie", "Französische Revolution", "Klimawandel",
    "Optik", "Photosynthese", "Programmiersprache", "Säure-Base-Konzepte", "Sinfonie",
]
GENERATED = {"akteure", "quellen", "glossar"}  # blocks 6, 12, 13: built by generators, not matched text
MARKER = re.compile(r"\[(\d{1,3})\]")
service = cli_service(ZIMS)


def norm(text: str) -> str:
    return " ".join(text.split())


def post(body: dict) -> tuple[float, dict]:
    data = json.dumps({**body, "extraction": "rule-based", "generation": "rule-based"}).encode("utf-8")
    request = urllib.request.Request(BASE + "/api/v2/compendium", data=data, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.loads(response.read())
    return time.perf_counter() - started, payload


rows = []
for topic in TOPICS:
    seconds, payload = post({"topic": topic, "parts": ["world"]})
    prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    chunk_text = {chunk.chunk_id: norm(chunk.text) for chunk in prepared.chunks}
    total = own = own_found = listed = listed_found = unknown_chunk = 0
    block_chars = 0
    misses: list[str] = []
    for section in payload["sections"]:
        if section["slot_key"] in GENERATED or not section.get("text"):
            continue
        block_chars += len(section["text"])
        cited = {c["number"]: c["chunk_id"] for c in section.get("citations") or []}
        block_texts = [chunk_text[cid] for cid in cited.values() if cid in chunk_text]
        unknown_chunk += sum(1 for cid in cited.values() if cid not in chunk_text)
        body = "\n".join(line for line in section["text"].splitlines() if not line.lstrip().startswith(("#", "|")))
        for paragraph in re.split(r"\n\s*\n", re.sub(r"<!--.*?-->", "", body, flags=re.S)):
            for unit in _units(paragraph):
                for sentence in _cited_sentences(unit):
                    plain = norm(MARKER.sub("", sentence)).strip()
                    if not plain.strip(" .;:,!?…()0123456789*"):
                        continue
                    total += 1
                    probe = plain.rstrip(" .")
                    numbers = [int(n) for n in MARKER.findall(sentence)]
                    if numbers:
                        own += 1
                        texts = [chunk_text.get(cited.get(n, ""), "") for n in numbers]
                        hit = any(probe in text for text in texts if text)
                        own_found += hit
                    else:
                        listed += 1
                        hit = any(probe in text for text in block_texts)
                        listed_found += hit
                    if not hit and len(misses) < 3:
                        misses.append(plain[:160])
    audit = payload["audit"]
    row = {
        "topic": topic, "seconds": round(seconds, 2), "sources": len(payload.get("sources") or []),
        "sections_filled": audit.get("sections_filled"), "sections_empty": audit.get("sections_empty"),
        "citations": audit.get("citations"), "block_chars": block_chars, "markdown_chars": len(payload["markdown"]),
        "sentences": total, "with_own_number": own, "own_in_cited_paragraph": own_found,
        "list_items": listed, "list_items_in_block_paragraphs": listed_found, "unknown_chunk_ids": unknown_chunk,
        "misses": misses, "resolved": payload.get("resolution", {}).get("title"),
    }
    rows.append(row)
    print(f"{topic:24s} {seconds:5.2f} s  Quellen {row['sources']:2d}  Sätze {total:3d}  mit Nummer {own:3d} "
          f"davon im zitierten Absatz {own_found:3d}  Listenpunkte {listed:2d} davon im Baustein belegt {listed_found:2d}"
          f"  unbekannte chunk_ids {unknown_chunk}", flush=True)

OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
S = sum(r["sentences"] for r in rows)
print(f"\nSätze {S}; mit eigener Nummer {sum(r['with_own_number'] for r in rows)}, davon im zitierten Absatz "
      f"{sum(r['own_in_cited_paragraph'] for r in rows)}; Listenpunkte {sum(r['list_items'] for r in rows)}, davon in "
      f"einem Absatz des Bausteins {sum(r['list_items_in_block_paragraphs'] for r in rows)}")
