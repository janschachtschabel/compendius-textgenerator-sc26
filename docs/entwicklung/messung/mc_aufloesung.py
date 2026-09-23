"""Topic resolution only (project venv): the main article of every query against the gold files of eval/artikelwahl.

Each query runs through CompendiumService.prepare with parts=["curricula"] and part 2 switched off in this process,
so the service normalises and resolves the topic exactly as for a compendium but builds no corpus. A resolution is correct
when its title is one of the expected titles or the target of a redirect Wikipedia sets for one of them.

With --llm the service gets the LLM of the b-api (gpt-5.6-luna, key from B_API_KEY) and resolves with
article_choice=llm (D35): the model decides where the rules are unsure, and the output adds how often it was asked
and the tokens of the choice. The rules alone are the run without --llm.

Usage: python mc_aufloesung.py <out.json> [--llm] <gold.yaml>...
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ARGS = sys.argv[1:]
USE_LLM = "--llm" in ARGS
if USE_LLM:
    os.environ["LLM_ENABLED"] = "true"
    os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
else:
    os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.knowledge.article_choice import ArticleChoiceJob  # noqa: E402
from app.service import TopicNotFoundError  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]

out_path, gold_paths = Path(ARGS[0]), [Path(p) for p in ARGS[1:] if p != "--llm"]
service = cli_service(ZIMS)
service.curricula = None  # without part 2, prepare stops after the resolution
wiki = service.registry.primary_archive
if USE_LLM and service.llm is None:
    raise SystemExit("--llm: LLM_ENABLED did not reach the settings")


def accepted(titles: list[str]) -> list[str]:
    found = list(titles)
    for title in titles:
        article = wiki.read(title) if wiki is not None else None
        if article is not None and article.title not in found:
            found.append(article.title)
    return found


results: dict[str, list[dict]] = {}
tokens = 0
for gold_path in gold_paths:
    rows = results.setdefault(gold_path.name, [])
    for entry in yaml.safe_load(gold_path.read_text(encoding="utf-8"))["anfragen"]:
        ok_titles = accepted(entry["erwartet"])
        choice = ArticleChoiceJob(service.llm.client, service.llm.open_budget()) if USE_LLM and service.llm else None
        asked = 0
        try:
            prepared = service.prepare(GenerateRequest(topic=entry["anfrage"], parts=["curricula"]), choice=choice)
            resolution = prepared.resolution
            if prepared.article_choice is not None:
                asked = prepared.article_choice.offered
                tokens += prepared.article_choice.total_tokens
        except TopicNotFoundError as exc:
            resolution = exc.resolution
        rows.append(
            {
                "anfrage": entry["anfrage"],
                "art": entry["art"],
                "akzeptiert": ok_titles,
                "titel": resolution.title,
                "richtig": resolution.title in ok_titles,
                "methode": resolution.method,
                "sicher": resolution.confident,
                "alternativen": resolution.alternatives,
                "begriffsklaerung": resolution.disambiguation,
                "llm_gefragt": bool(asked),
            }
        )

for name, rows in results.items():
    by_kind: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        by_kind[row["art"]].append(row["richtig"])
    summary = ", ".join(f"{kind} {sum(flags)}/{len(flags)}" for kind, flags in by_kind.items())
    asked = sum(row["llm_gefragt"] for row in rows)
    print(f"{name}: {sum(r['richtig'] for r in rows)} von {len(rows)} richtig ({summary}); LLM gefragt: {asked}")
    for row in rows:
        if not row["richtig"]:
            print(f"   {row['anfrage']:40s} -> {row['titel']} ({row['methode']})")
if USE_LLM:
    print(f"Token der Artikelwahl: {tokens}")
out_path.write_text(json.dumps({"tokens": tokens, "ergebnisse": results}, ensure_ascii=False, indent=1), "utf-8")
