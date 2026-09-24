"""The decisions laya is tested on (M16), as the service would pose them (project venv, no LLM, no tokens).

1. Article choice: every query of the three gold sets in eval/artikelwahl resolves through CompendiumService.prepare.
   Where the rules are unsure, a recording chooser stands in for the LLM: it keeps the (title, opening) candidates the
   registry offers, exactly what article_choice=llm would see, and leaves the rules' article in place.
2. Hit check: the 47 full-text hits of the 20 topics of M1 with their blind relevance notes (m10_trefferfilter.json),
   each with its opening and the opening of the topic's main article.

The output holds openings of Wikipedia articles and stays outside the repository; mc_laya.py reads it.

Usage: python mc_laya_export.py <ergebnisse-dir> <out.json> <gold.yaml>...
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

os.environ.pop("LLM_ENABLED", None)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import app.service as service_module
from app.cli_common import cli_service
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import ArticleChoiceJob
from app.service import TopicNotFoundError
from app.sources.zim.topic_rules import opening

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
results_dir, out_path, gold_paths = Path(sys.argv[1]), Path(sys.argv[2]), [Path(p) for p in sys.argv[3:]]

service = cli_service(ZIMS)
service.curricula = None  # without part 2, prepare stops after the resolution
wiki = service.registry.primary_archive
assert wiki is not None
offered: list[list[tuple[str, str]]] = []


class RecordingChooser:
    """Stands in for LlmArticleChooser: keeps the candidates and leaves the rules' decision."""

    def __init__(self, job: object, topic: str, subject: str | None) -> None:
        self.topic, self.subject = topic, subject
        self.report = None  # prepare reads it; nothing was asked

    def __call__(self, candidates: list[tuple[str, str]]) -> tuple[int | None, str | None]:
        offered.append(list(candidates))
        return None, None


service_module.LlmArticleChooser = RecordingChooser  # type: ignore[misc,assignment]


def accepted(titles: list[str]) -> list[str]:
    """The gold titles and the articles their redirects lead to, as M9 counts them."""
    found = list(titles)
    for title in titles:
        article = wiki.read(title)
        if article is not None and article.title not in found:
            found.append(article.title)
    return found


def lead_of(title: str) -> str | None:
    article = wiki.read(title)
    return None if article is None else opening(wiki.parse(article).text)


choices = []
for gold_path in gold_paths:
    for entry in yaml.safe_load(gold_path.read_text(encoding="utf-8"))["anfragen"]:
        offered.clear()
        request = GenerateRequest(topic=entry["anfrage"], parts=["curricula"])
        job = ArticleChoiceJob(None, None)  # type: ignore[arg-type] - the recording chooser never calls it
        try:
            resolution = service.prepare(request, choice=job).resolution
        except TopicNotFoundError as exc:
            resolution = exc.resolution
        if not offered:  # sure, or nothing to weigh
            continue
        normalized = service_module.normalize_topic(entry["anfrage"])
        choices.append(
            {
                "goldsatz": gold_path.name,
                "anfrage": entry["anfrage"],
                "thema": normalized.topic,
                "fach": normalized.subject,
                "akzeptiert": accepted(entry["erwartet"]),
                "regeln": resolution.title,
                "kandidaten": [{"titel": t, "anfang": o} for t, o in offered[0]],
            }
        )

hits = []
for row in json.loads((results_dir / "m10_trefferfilter.json").read_text(encoding="utf-8")):
    main = service.registry.resolve_topic(row["thema"])
    hits.append(
        {
            "thema": row["thema"],
            "titel": row["titel"],
            "note": row["note"],
            "anfang": lead_of(row["titel"]),
            "hauptartikel": main.title,
            "hauptartikel_anfang": lead_of(main.title) if main.title else None,
        }
    )

out_path.write_text(json.dumps({"artikelwahl": choices, "treffer": hits}, ensure_ascii=False, indent=1), "utf-8")
print(f"Artikelwahl: {len(choices)} unsichere Anfragen, {sum(len(c['kandidaten']) for c in choices)} Kandidaten; "
      f"Treffer: {len(hits)}, ohne Anfang {sum(h['anfang'] is None for h in hits)}")
