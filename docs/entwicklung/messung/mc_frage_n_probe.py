"""Probe for M49 (V1, V3): what the question N (D63) names as the overview of a topic, with fresh answers, whether the
archive has it, and (prompt v2) whether the model says it covers the topic as asked. The code that runs is the one on
PYTHONPATH: the main checkout for prompt v1, the worktree for v2. Run from the project folder.

Usage: python mc_frage_n_probe.py <out.json> <rounds>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.knowledge.article_choice import ArticleChoiceJob  # noqa: E402
from app.knowledge.topic_articles import ask_topic_articles  # noqa: E402
from app.llm.prompts import get_prompt  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GOLD = Path(r"C:\Users\jan\staging\Windsurf\compendious-text-fastapi\eval\artikelwahl\korpus_labels.yaml")
KINDS = {
    "M48 einfach": ["Optik", "Photosynthese", "Französische Revolution"],
    "M48 Sammelthema": ["Dichter aus dem Mittelalter", "Komponisten der Klassik", "Philosophen der Aufklärung"],
    "M48 Aspekt": ["OER-Förderungen", "Inklusion im Sportunterricht", "Künstliche Intelligenz im Unterricht"],
    "M37 Sammel- und Mischthema": [
        "deutsche Dichter", "Dichter der Romantik", "Komponisten der Klassik", "Philosophen der Aufklärung",
        "Maler des Impressionismus", "römische Kaiser", "deutsche Bundeskanzler", "griechische Götter",
        "Planeten des Sonnensystems", "Edelgase", "Weltreligionen", "erneuerbare Energien",
        "Erfindungen der Industrialisierung", "Nobelpreisträger für Physik", "Frauen in der Wissenschaft",
        "Märchen der Brüder Grimm", "deutsche Flüsse", "Säugetiere des Waldes", "Vulkane Europas",
        "Entdecker der Neuzeit", "Klimawandel und Landwirtschaft", "Mathematik in der Musik", "Chemie im Alltag",
        "Frauen im Mittelalter", "Musik der Romantik",
    ],
    "gewöhnlich (M39)": list(yaml.safe_load(GOLD.read_text(encoding="utf-8"))["labels"]),
}  # fmt: skip


def main() -> None:
    out, rounds = Path(sys.argv[1]), int(sys.argv[2])
    service = cli_service(ZIMS)
    llm = service.llm
    if llm is None:
        raise SystemExit("no LLM")
    archive = service.registry.primary_archive
    version = get_prompt("topic_articles").version
    rows = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    done = {(r["kind"], r["topic"], r["round"]) for r in rows}
    for kind, topics in KINDS.items():
        for topic in topics:
            for round_ in range(rounds):
                if (kind, topic, round_) in done:
                    continue
                job = ArticleChoiceJob(llm.client, llm.open_budget(), None)
                report = ask_topic_articles(job, archive, topic)
                rows.append({
                    "kind": kind, "topic": topic, "round": round_, "prompt": version,
                    "overview": report.overview, "overview_title": report.overview_title,
                    "covers": getattr(report, "covers", None), "found": report.found[:4],
                    "fallback": report.fallback, "tokens": report.total_tokens,
                })
                print(f"v{version} {kind[:10]:10s} {topic[:30]:30s} {round_} {report.overview!r} -> "
                      f"{report.overview_title!r} covers={getattr(report, 'covers', None)}", flush=True)
                out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
