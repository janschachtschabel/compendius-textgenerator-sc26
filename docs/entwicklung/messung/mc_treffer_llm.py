"""The M8 judge as a filter for the full-text hits of the corpus (project venv, b-api, gpt-5.6-luna).

For the 20 normal topics of eval/artikelwahl/hauptartikel.yaml the service builds its corpus; the articles that came
in as full-text hits for a block (origin "search") go to the model in one call per topic, with the prompt of
mc_artikel_richter.py unchanged: title and the beginning of the text (180 characters), on the scale of the gold. The
hits it rates 0 would be dropped. The output sets its ratings against the blind labels of
eval/artikelwahl/korpus_labels.yaml and counts what dropping them removes of the paragraphs the standard strategy
printed in M8 (ergebnisse/m8_artikelwahl.json).

With --korpus the model rates every article of the corpus in the call, as the judge rated the whole pool, and only
the full-text hits it rates 0 would be dropped; without it the call holds the hits alone.

Usage: python mc_treffer_llm.py <out.json> [--korpus]
"""

from __future__ import annotations

import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

import yaml

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
ROOT = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi")
EVAL = ROOT / "eval" / "artikelwahl"
M8 = ROOT / "docs" / "entwicklung" / "messung" / "ergebnisse" / "m8_artikelwahl.json"
OPENING_CHARS = 180  # as in mc_artikel_richter.py
LEAD_CHARS = 300  # the opening of the pool in mc_artikelwahl.py
SEED = 20260923
SYSTEM = (  # mc_artikel_richter.py, unchanged
    "Du beurteilst, welche Lexikonartikel in ein Kompendium für Lehrkräfte zu einem Unterrichtsthema gehören. "
    "Vergib je Artikel eine Note: 2 = gehört zum Thema (das Thema selbst, ein Teilgebiet, ein Kernbegriff, ein "
    "zentraler Vorgang, ein zentrales Ereignis oder eine Person, deren Bedeutung im Thema liegt); 1 = verwandt "
    "(Nachbarthema, direkter Oberbegriff, Hintergrund, einzelnes Werk als Beispiel, Person mit breiterem Wirken, "
    "allgemeiner Artikel zu einem beteiligten Stoff); 0 = passt nicht (andere Bedeutung, Begriffsklärung, Liste, "
    "Film gleichen Namens, weit entfernter Oberbegriff oder kein erkennbarer Bezug). Antworte ausschließlich mit "
    'einem JSON-Objekt, das jede Artikel-ID auf ihre Note abbildet, zum Beispiel {"a1": 2, "a2": 0}.'
)

out_path = Path(sys.argv[1])
WHOLE_CORPUS = "--korpus" in sys.argv[2:]
service = cli_service(ZIMS)
assert service.llm is not None, "LLM_ENABLED did not reach the settings"
client = service.llm.client
labels = yaml.safe_load((EVAL / "korpus_labels.yaml").read_text(encoding="utf-8"))["labels"]
entries = yaml.safe_load((EVAL / "hauptartikel.yaml").read_text(encoding="utf-8"))["anfragen"]
topics = [e["anfrage"] for e in entries if e["art"] == "normal"]
printed = {(t, a["titel"]): a["gedruckt"] for t, c in json.loads(M8.read_text("utf-8"))["korpus"].items()
           for a in c["artikel"]}

rows: list[dict] = []
tokens = calls = 0
for topic in topics:
    prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    picked = service.registry.build_corpus(
        prepared.resolution, slots=prepared.template.content_slots(), max_articles=service.settings.corpus_max_articles
    )
    hits = [s for s in picked if s.origin == "search"]
    if not hits:
        continue
    rated = picked if WHOLE_CORPUS else hits  # the whole corpus gives the model the strong articles to compare
    keys = sorted(f"{s.project}:{s.title}" for s in rated)
    random.Random(f"{SEED}:{topic}").shuffle(keys)
    openings = {f"{s.project}:{s.title}": " ".join(s.lead_text.split())[:LEAD_CHARS] for s in rated}
    searched = {f"{s.project}:{s.title}" for s in hits}
    alias = {f"a{i + 1}": key for i, key in enumerate(keys)}
    listing = "\n".join(f"{a}: {key.split(':', 1)[1]} — {openings[key][:OPENING_CHARS]}" for a, key in alias.items())
    user = f"Thema des Kompendiums: {topic}\n\nArtikel:\n{listing}\n\nGib das JSON-Objekt zurück."
    answer = client.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        max_output_tokens=client.completion_limit(12 * len(keys)),
    )
    tokens += answer.total_tokens
    calls += 1
    text = answer.text
    notes = json.loads(text[text.find("{") : text.rfind("}") + 1])
    for a, key in alias.items():
        if key not in searched:
            continue
        title = key.split(":", 1)[1]
        rows.append({
            "thema": topic, "titel": title, "gold": labels.get(topic, {}).get(key), "llm": notes.get(a),
            "gedruckt_m8": printed.get((topic, title), 0),
        })

cross = Counter((r["gold"], r["llm"]) for r in rows)
kept, dropped, kept_p, dropped_p = Counter(), Counter(), Counter(), Counter()
for r in rows:
    if r["llm"] == 0:
        dropped[r["gold"]] += 1
        dropped_p[r["gold"]] += r["gedruckt_m8"]
    else:
        kept[r["gold"]] += 1
        kept_p[r["gold"]] += r["gedruckt_m8"]
print(f"Volltexttreffer: {len(rows)} in {calls} Aufrufen, {tokens} Token")
print("Gold x LLM:", dict(sorted(cross.items(), key=str)))
print(f"LLM-0 verwerfen: Artikel behalten 2/1/0 {kept[2]}/{kept[1]}/{kept[0]}, verworfen {dropped[2]}/{dropped[1]}/{dropped[0]}")
print(f"   in M8 gedruckte Absätze behalten 2/1/0 {kept_p[2]}/{kept_p[1]}/{kept_p[0]}, "
      f"verworfen {dropped_p[2]}/{dropped_p[1]}/{dropped_p[0]}")
for r in rows:
    if r["llm"] == 0 or r["gold"] == 0:
        print(f"   Gold {r['gold']} LLM {r['llm']}  {r['thema']}: {r['titel']}")
out_path.write_text(json.dumps({"tokens": tokens, "calls": calls, "treffer": rows}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
