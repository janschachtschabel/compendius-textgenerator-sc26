"""M40, a way without any model: llm-free with the main article and its twin only (max_articles 2).

In M40 the small local models raised the share of fitting paragraphs although they named few articles of the archive:
where they named nothing but the topic, the corpus was the main article alone, without the linked sub-articles and
full-text hits of llm-free, which are often only related. R2 asks what that alone does, with a request parameter the
service has today: max_articles 2 keeps the main article and its twin and nothing else (ZimRegistry.build_corpus).

Runs in the development container as M38 and M40 did, MODEL2VEC_PATH empty, so the grades of M37 apply.

Usage (in the container, with this file, mc_sammelthemen.py and eval/artikelwahl/korpus_labels.yaml in one directory
on PYTHONPATH): python mc_sammelthemen_nur_haupt.py <dir> <out.json> <sheet.json> [--normal]
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

os.environ["MODEL2VEC_PATH"] = ""  # the matching of M37, so its grades apply
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import yaml  # noqa: E402

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import Compendium  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

directory, out_path, sheet_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
m37 = ast.parse((directory / "mc_sammelthemen.py").read_text(encoding="utf-8"))
TOPICS: list[str] = next(
    ast.literal_eval(n.value)
    for n in m37.body
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "TOPICS"
)
if "--normal" in sys.argv:
    TOPICS = list(yaml.safe_load((directory / "korpus_labels.yaml").read_text(encoding="utf-8"))["labels"])
service = cli_service(None)


def summary(result: Compendium, sheet: dict[str, str]) -> dict[str, Any]:
    """What the way printed, per article, as M37, M38 and M40; the leads go to the sheet only."""
    by_id = {source.source_id: source for source in result.sources}
    printed: Counter[str] = Counter()
    for section in result.sections:
        for chunk_id in section.chunk_ids:
            source = by_id[chunk_id.rsplit(":c", 1)[0]]
            printed[source.title] += 1
            sheet.setdefault(source.title, source.lead[:400])
    return {
        "hauptartikel": result.resolution.title,
        "gedruckt": [{"titel": t, "absaetze": n} for t, n in printed.most_common()],
        "bausteine": result.audit.sections_filled,
    }


rows: list[dict[str, Any]] = []
sheets: dict[str, dict[str, str]] = {}
for topic in TOPICS:
    request = GenerateRequest(topic=topic, parts=["world"], preset="llm-free", max_articles=2)  # type: ignore[arg-type]
    started = time.perf_counter()
    result = service.generate(request)
    way = {"sekunden": round(time.perf_counter() - started, 2), **summary(result, sheets.setdefault(topic, {}))}
    rows.append({"thema": topic, "wege": {"R2": way}})
    print(f"{topic:36s} {way['hauptartikel']}  {sum(e['absaetze'] for e in way['gedruckt'])} Absätze", flush=True)

out_path.write_text(json.dumps({"themen": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
sheet_path.write_text(json.dumps(sheets, ensure_ascii=False, indent=1), encoding="utf-8")
