"""M39: the question N built into balanced (D63), measured through the service on the topics of M37.

M37 measured N as a prototype: the named articles alone were the corpus, the first one the main article. Built in as
option C of the decision paper (point 9), N replaces the main article only where the rules missed the topic, keeps the
Klexikon twin and fills the corpus up to CORPUS_MAX_ARTICLES; without a usable answer the corpus is the one of before.
This runs every topic of M37 through part 1 of balanced as a request would, with the prompt of M37 word for word: the
b-api answers from its cache what it answered in M37 (same titles, reported tokens, 0.1 to 0.3 s), so what changes is
what the building in changed. Every article printed that M37 did not grade is graded blind as there.

Runs from the project folder like M37, without Model2Vec, so the matching is that of M37 and its grades apply. The
output holds titles, counts, tokens and milliseconds; the leads go to the sheet only.

Usage (from the project folder): python mc_n_dienst.py <out.json> <sheet.json> [--normal]
"""

from __future__ import annotations

import ast
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ["MODEL2VEC_PATH"] = ""  # as M37 ran
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import yaml  # noqa: E402

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import Compendium  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
HERE = Path(__file__).parent
m37 = ast.parse((HERE / "mc_sammelthemen.py").read_text(encoding="utf-8"))
TOPICS: list[str] = next(
    ast.literal_eval(n.value)
    for n in m37.body
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "TOPICS"
)
if "--normal" in sys.argv:
    TOPICS = list(yaml.safe_load(Path("eval/artikelwahl/korpus_labels.yaml").read_text(encoding="utf-8"))["labels"])
out_path, sheet_path = Path(sys.argv[1]), Path(sys.argv[2])
service = cli_service(ZIMS)
if service.llm is None:
    raise SystemExit("LLM_ENABLED did not reach the settings")


def summary(result: Compendium, sheet: dict[str, str]) -> dict[str, Any]:
    """What balanced printed, per article, as M37; what the article choice asked; the leads go to the sheet."""
    by_id = {source.source_id: source for source in result.sources}
    printed: Counter[str] = Counter()
    for section in result.sections:
        for chunk_id in section.chunk_ids:
            source = by_id[chunk_id.rsplit(":c", 1)[0]]
            printed[source.title] += 1
            sheet.setdefault(source.title, source.lead[:400])
    choice = (result.audit.llm or {}).get("article_choice") or {}
    return {
        "hauptartikel": result.resolution.title,
        "methode": result.resolution.method,
        "sicher": result.resolution.confident,
        "gedruckt": [{"titel": t, "absaetze": n} for t, n in printed.most_common()],
        "bausteine": result.audit.sections_filled,
        "artikelwahl": {key: choice.get(key) for key in (
            "used", "asked", "chosen", "hits_checked", "hits_dropped",
            "articles_asked", "articles_found", "articles_main", "articles_fallback",
        )},  # fmt: skip
        "tokens": result.audit.llm_tokens or {},
        "ms": result.audit.timings_ms,
    }


rows: list[dict[str, Any]] = []
sheets: dict[str, dict[str, str]] = {}
for topic in TOPICS:
    result = service.generate(GenerateRequest(topic=topic, parts=["world"], preset="balanced"))  # type: ignore[arg-type]
    way = summary(result, sheets.setdefault(topic, {}))
    rows.append({"thema": topic, "wege": {"C": way}})
    found = way["artikelwahl"]["articles_found"] or []
    print(f"{topic:36s} {way['hauptartikel']} ({way['methode']})  N: {len(found)} Artikel"
          f"{'  Rückfall: ' + str(way['artikelwahl']['articles_fallback']) if not found else ''}", flush=True)  # fmt: skip

out_path.write_text(json.dumps({"themen": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
sheet_path.write_text(json.dumps(sheets, ensure_ascii=False, indent=1), encoding="utf-8")
