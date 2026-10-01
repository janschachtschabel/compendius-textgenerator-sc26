"""M49 (V3) without tokens: the hint of the word rule (llm-free, no N) on the 94 gold queries of the article choice
and on the nine topics of M48, with the rules' resolution. Run from the worktree with PYTHONPATH=.

Usage: python mc_hinweis_wortregel.py <out.json>  (from the branch m49-proben: it imports its lint rule)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.knowledge.topic import normalize_topic, topic_as_asked  # noqa: E402
from app.synthesis.lint import topic_scope_finding  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\artikelwahl")
M48 = {
    "M48 einfach": ["Optik", "Photosynthese", "Französische Revolution"],
    "M48 Sammelthema": ["Dichter aus dem Mittelalter", "Komponisten der Klassik", "Philosophen der Aufklärung"],
    "M48 Aspekt": ["OER-Förderungen", "Inklusion im Sportunterricht", "Künstliche Intelligenz im Unterricht"],
}


def main() -> None:
    service = cli_service(ZIMS)
    registry, catalog = service.registry, service.subjects
    queries = []
    for name in ("hauptartikel.yaml", "hauptartikel_validierung.yaml", "hauptartikel_test.yaml"):
        for entry in yaml.safe_load((GOLD / name).read_text(encoding="utf-8"))["anfragen"]:
            queries.append((entry["art"], entry["anfrage"]))
    queries += [(kind, topic) for kind, topics in M48.items() for topic in topics]
    rows = []
    for kind, query in queries:
        normalized = normalize_topic(query, is_subject=catalog.knows)
        resolution = registry.resolve_topic(normalized.topic, context=normalized.context, query=normalized.query)
        finding = topic_scope_finding(
            topic_as_asked(normalized),
            resolution.title,
            normalized=normalized.topic,
            covers=None,
            method=resolution.method,
            about_topic=False,
        )
        rows.append({"kind": kind, "query": query, "title": resolution.title, "method": resolution.method,
                     "hint": finding is not None})
        print(f"{kind[:24]:24s} {query[:34]:34s} -> {str(resolution.title)[:34]:34s} {resolution.method!s:14s} "
              f"{'HINWEIS' if finding else ''}")
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
