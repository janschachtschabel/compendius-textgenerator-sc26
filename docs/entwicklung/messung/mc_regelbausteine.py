"""M50, beside the wording: how large the blocks are that the rules build in every profile (actors, sources,
glossary) against the content blocks - balanced on the nine topics of M48, whose corpus is built as in the profiles
above it (the article choice and question N). About 600 tokens per topic; the key comes from B_API_KEY.

Usage (from the project folder): python mc_regelbausteine.py <out.json>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
TOPICS = [
    "Optik",
    "Photosynthese",
    "Französische Revolution",
    "Dichter aus dem Mittelalter",
    "Komponisten der Klassik",
    "Philosophen der Aufklärung",
    "OER-Förderungen",
    "Inklusion im Sportunterricht",
    "Künstliche Intelligenz im Unterricht",
]


def main() -> None:
    service = cli_service(ZIMS)
    rows = []
    for topic in TOPICS:
        result = service.generate(GenerateRequest(topic=topic, parts=["world"], preset="balanced"))
        sections = [{"title": s.title, "status": str(s.status), "chars": len(s.text or "")} for s in result.sections]
        rows.append({"topic": topic, "sections": sections})
        print(topic, [(s["title"][:14], s["status"][:12], s["chars"]) for s in sections], flush=True)
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
