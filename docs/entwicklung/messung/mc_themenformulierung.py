"""M51: what the model words as the topic of a text (D72) - questions, sentences and long topics, some of them with a
material beside them, real materials of WLO without a topic (M21) and collections of the staging repository - with the
prompt topic_wording through the b-api, as the writing profiles ask it. The key comes from B_API_KEY; about 1,000
tokens per input.

Usage (from the project folder): python mc_themenformulierung.py <out.json> [<materials>]
  <materials>: how many materials of eval/materialwahl/materialien.yaml (default 12, those with a topic first)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.cli_common import cli_service  # noqa: E402
from app.knowledge.article_choice import ArticleChoiceJob  # noqa: E402
from app.knowledge.topic_wording import TopicWordingReport, Metadata, word_topic, wording_request  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
TEXTS = [  # a teacher's words in place of a topic: questions, sentences, a topic longer than one
    "Wie funktioniert die Photosynthese bei Pflanzen?",
    "Warum ist der Himmel blau?",
    "Ich möchte mit meiner 8. Klasse über die Ursachen des Ersten Weltkriegs sprechen.",
    "Die Schülerinnen und Schüler sollen verstehen, wie eine repräsentative Demokratie funktioniert und welche Rolle "
    "Wahlen spielen.",
    "Material zur Lichtbrechung an Linsen für den Physikunterricht der Sekundarstufe I mit Experimenten",
    "Förderprogramme für offene Bildungsmaterialien in Deutschland und Europa seit 2015",
    "Was müssen Lehrkräfte über Künstliche Intelligenz im Unterricht wissen?",
    "Inklusion im Sportunterricht: Wie gelingt gemeinsames Bewegen von Kindern mit und ohne Behinderung?",
]
COLLECTIONS = [  # collections of the staging repository the examples of the API name
    "9e7ae956-e9df-430f-bace-f3db4b910013",
    "d38101c1-9a43-414b-a51f-e2dcff0add44",
    "f35c17d1-a29e-4b26-9d22-802682fad43d",
]


def ask(job: ArticleChoiceJob, topic: str | None, beside: Metadata | None, extra: dict[str, Any]) -> dict[str, Any]:
    wanted = wording_request(topic, beside)
    row: dict[str, Any] = {"topic": topic, "beside": getattr(beside, "title", None), **extra}
    if wanted is None:
        return {**row, "worded": None, "note": "kein Text: das Thema bleibt"}
    report = TopicWordingReport(source=wanted.source, reason=wanted.reason)
    started = time.monotonic()
    worded = word_topic(job, wanted.text, report)
    return {
        **row,
        "source": report.source,
        "reason": report.reason,
        "worded": worded,
        "fallback": report.fallback,
        "tokens": report.total_tokens,
        "s": round(time.monotonic() - started, 1),
    }


def main() -> None:
    out = Path(sys.argv[1])
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    service = cli_service(ZIMS)
    if service.llm is None:
        raise SystemExit("LLM_ENABLED did not reach the settings")
    job = ArticleChoiceJob(service.llm.client, service.llm.open_budget(400_000))
    rows = [ask(job, text, None, {"kind": "Text"}) for text in TEXTS]
    gold = yaml.safe_load((ROOT / "eval" / "materialwahl" / "materialien.yaml").read_text(encoding="utf-8"))
    entries = sorted(gold["materialien"], key=lambda m: m.get("art") != "klar")[:count]
    nodes = []
    for entry in entries:
        try:
            info, _ = service.read_node(entry["node_id"], entry.get("repository"))
        except Exception as exc:  # noqa: BLE001 - a measurement records the failure and goes on
            rows.append({"kind": "Material", "node_id": entry["node_id"], "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        nodes.append(info)
        extra = {"kind": "Material", "art": entry.get("art"), "begriff": entry.get("begriff")}
        rows.append(ask(job, None, info, extra))
    for text, info in zip(TEXTS[:3], nodes[:3], strict=False):  # a text as topic with a material beside it
        rows.append(ask(job, text, info, {"kind": "Text mit Material"}))
    for collection_id in COLLECTIONS:
        try:
            info, _ = service.read_node(collection_id)
        except Exception as exc:  # noqa: BLE001
            rows.append({"kind": "Sammlung", "node_id": collection_id, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        rows.append(ask(job, None, info, {"kind": "Sammlung"}))
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for row in rows:
        shown = row.get("topic") or row.get("beside") or row.get("node_id")
        print(f"{row['kind']:18s} | {str(shown)[:70]:70s} -> {row.get('worded') or row.get('fallback') or row.get('error')}")


if __name__ == "__main__":
    main()
