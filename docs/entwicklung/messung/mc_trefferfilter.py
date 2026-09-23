"""Full-text hits per block (project venv): which filter keeps the articles that fit and drops the ones that do not.

For the 20 normal topics of eval/artikelwahl/hauptartikel.yaml the service builds its corpus as for a compendium.
Every article that came in as a full-text hit for a block (origin "search") is matched with its blind relevance label
from eval/artikelwahl/korpus_labels.yaml (2 belongs to the topic, 1 related, 0 does not fit) and described by what a
filter could look at: the stem of the topic in the title, in the first sentence, every content word of the topic in
title and lead, and the Model2Vec similarity of its lead to the lead of the main article. The output counts, per
candidate filter, the hits it keeps and drops by label.

Usage: python mc_trefferfilter.py <out.json>
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import yaml

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.knowledge.topic import topic_stem  # noqa: E402
from app.matching.embeddings import _load_model  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
EVAL = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\artikelwahl")
M2V = "JanSchachtschabel/m2v-gte-256-edu"
WORD = re.compile(r"[a-zäöüß]{4,}")

out_path = Path(sys.argv[1])
service = cli_service(ZIMS)
labels = yaml.safe_load((EVAL / "korpus_labels.yaml").read_text(encoding="utf-8"))["labels"]
topics = [e["anfrage"] for e in yaml.safe_load((EVAL / "hauptartikel.yaml").read_text("utf-8"))["anfragen"]]
topics = [t for t, e in zip(topics, yaml.safe_load((EVAL / "hauptartikel.yaml").read_text("utf-8"))["anfragen"],
                            strict=True) if e["art"] == "normal"]
model = _load_model(M2V)


def first_sentence(text: str) -> str:
    return " ".join(text.split()).split(". ")[0][:300]


def unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


rows: list[dict] = []
for topic in topics:
    prepared = service.prepare(GenerateRequest(topic=topic, parts=["world"]))
    picked = service.registry.build_corpus(
        prepared.resolution, slots=prepared.template.content_slots(), max_articles=service.settings.corpus_max_articles
    )
    primary = picked[0]
    stem = topic_stem(primary.title)
    words = [w[:-1] if len(w) > 5 else w for w in WORD.findall(re.sub(r"\s*\(.*\)$", "", primary.title).lower())]
    main_vec = unit(model.encode([primary.lead_text[:2000]])[0])
    for source in picked:
        if source.origin != "search":
            continue
        lead = source.lead_text
        haystack = f"{source.title} {lead}".lower()
        vector = unit(model.encode([lead[:2000]])[0])
        rows.append({
            "thema": topic,
            "titel": source.title,
            "note": labels.get(topic, {}).get(f"{source.project}:{source.title}"),
            "stamm": stem,
            "stamm_im_titel": stem in source.title.lower(),
            "stamm_im_ersten_satz": stem in first_sentence(lead).lower(),
            "alle_woerter": all(w in haystack for w in words),
            "m2v": round(float(main_vec @ vector), 3),
            "verlinkt": source.title in primary.links,
        })

missing = [r for r in rows if r["note"] is None]
labelled = [r for r in rows if r["note"] is not None]
print(f"Volltexttreffer: {len(rows)}, mit Note: {len(labelled)}, ohne Note: {len(missing)}")
print("Noten:", dict(sorted(Counter(r["note"] for r in labelled).items())))


def report(name: str, keep) -> None:  # type: ignore[no-untyped-def]
    kept = Counter(r["note"] for r in labelled if keep(r))
    dropped = Counter(r["note"] for r in labelled if not keep(r))
    print(f"{name:42s} behalten 2/1/0: {kept[2]:2d}/{kept[1]:2d}/{kept[0]:2d}   verworfen 2/1/0: "
          f"{dropped[2]:2d}/{dropped[1]:2d}/{dropped[0]:2d}")


report("heute (Stamm in Titel oder Einleitung)", lambda r: True)
report("Stamm im Titel", lambda r: r["stamm_im_titel"])
report("Stamm im Titel oder ersten Satz", lambda r: r["stamm_im_titel"] or r["stamm_im_ersten_satz"])
report("alle Themenwörter in Titel und Einleitung", lambda r: r["alle_woerter"])
for threshold in (0.3, 0.4, 0.5, 0.6, 0.7):
    report(f"Model2Vec >= {threshold}", lambda r, t=threshold: r["m2v"] >= t)
report("Titel/erster Satz und alle Themenwörter", lambda r: (r["stamm_im_titel"] or r["stamm_im_ersten_satz"])
       and r["alle_woerter"])
print("\nje Treffer (Note, Model2Vec, Stamm im Titel/ersten Satz, alle Wörter):")
for r in sorted(labelled, key=lambda r: (r["thema"], -r["m2v"])):
    print(f"  {r['note']} {r['m2v']:.2f} {'T' if r['stamm_im_titel'] else '-'}{'S' if r['stamm_im_ersten_satz'] else '-'}"
          f"{'W' if r['alle_woerter'] else '-'} {r['thema'][:22]:22s} {r['titel']}")
for r in missing:
    print(f"  ohne Note: {r['thema']}: {r['titel']}")
out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
