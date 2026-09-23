"""Checks behind statements of the documentation (project venv, no language model).

1. Main article and disambiguation pages in the corpora of the ten gold topics.
2. Same request twice on the server: same markdown apart from the timestamp?
3. F1 per building block for the default strategy with the 2.0.0 code (from the gold export).

Usage (project venv): python final_checks.py <base-url of the server>
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

from app.cli_common import cli_service
from app.domain.requests import GenerateRequest
from app.matching.eval import aggregate, evaluate

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
BASE = sys.argv[1].rstrip("/")
DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
TOPICS = [
    "Barockliteratur", "Bruchrechnung", "Demokratie", "Französische Revolution", "Klimawandel",
    "Optik", "Photosynthese", "Programmiersprache", "Säure-Base-Konzepte", "Sinfonie",
]

service = cli_service(ZIMS)
by_project = {a.project: a for a in service.registry.archives}
print("1) Hauptartikel und Begriffsklärungen im Korpus")
total_sources = bkl = 0
for topic in TOPICS:
    prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    titles = [(s.project, s.title) for s in prepared.sources]
    for project, title in titles:
        archive = by_project.get(project)
        if archive is None:
            continue
        article = archive.read(title)
        if article is not None and archive.parse(article).is_disambiguation:
            bkl += 1
    total_sources += len(titles)
    primary = next(s.title for s in prepared.sources if s.is_primary)
    print(f"   {topic:24s} Hauptartikel {primary!r:28s} Quellen {len(titles):2d}")
print(f"   Quellen gesamt {total_sources}, davon Begriffsklärungsseiten {bkl}")

print("2) Gleiche Anfrage zweimal (Server, regelbasiert)")
body = json.dumps({"topic": "Photosynthese", "parts": ["world", "curricula"], "extraction": "rule-based",
                   "generation": "rule-based"}).encode("utf-8")
texts = []
for _ in range(2):
    request = urllib.request.Request(BASE + "/api/v2/compendium", data=body,
                                     headers={"Content-Type": "application/json"})
    markdown = json.loads(urllib.request.urlopen(request, timeout=120).read())["markdown"]
    texts.append(re.sub(r"(?m)^generated_at: .*$", "", markdown))
print(f"   identisch bis auf generated_at: {texts[0] == texts[1]} ({len(texts[0])} Zeichen)")

print("3) F1 je Baustein, hybrid_light + M2V, voller Pool")
export = json.load(open(HERE / "mc_export_v200.json", encoding="utf-8"))
results = []
for topic in export["topics"]:
    slot_keys = [s["slot"] for s in topic["slots"] if not s.get("generator")]
    run = topic["mine"]["full"]["hybrid_light + M2V"]
    results.append(evaluate(topic["topic"], topic["gold"], run["classified"], slot_keys, matcher="hybrid_light + M2V"))
total = aggregate(results)
print(f"   macro {total.macro_f1:.3f} micro {total.micro_f1:.3f}")
for metrics in total.slots:
    print(f"   {metrics.slot:28s} Gold-Absätze {metrics.support:3d}  F1 {metrics.f1:.2f}")
