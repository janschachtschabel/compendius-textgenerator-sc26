"""Before N is built (decision paper, point 9, option C): does its overview keep the article choice on the gold right?

In option C the question N of M37 replaces the main article only where the rules do not hit a topic: their article
is a title suggestion or a full-text hit, or a list page. Every query of eval/artikelwahl runs through the rules
(choose_main_article without a job, as llm-free); where one of these holds, N is asked with the prompt of M37 word
for word, its titles are looked up as in M37 (the first one found becomes the main article), and the result is
compared with the expected titles. A title counts when it is expected or the target of a redirect Wikipedia sets for
an expected one (as in M35). Everywhere else N leaves the main article as it is, so the choice there stays the one of
M35.

The output holds titles, tokens and seconds, no article text. The b-api answers a prompt it has seen before from its
cache (M37 asked "Atommodell" already).

Usage (from the project folder): python mc_n_artikelwahl.py <out.json> <gold.yaml>...
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

from alter_linker import variations  # noqa: E402

from app.cli_common import cli_service  # noqa: E402
from app.knowledge.article_choice import read_object  # noqa: E402
from app.knowledge.main_article import choose_main_article  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
GUESSED = {"suggestion", "search"}
MAX_NAMED = 8
# M37 (mc_sammelthemen.py), word for word
NEW_SYSTEM = (
    "Du hilfst, für ein Unterrichtsthema die Artikel der deutschsprachigen Wikipedia auszuwählen, aus denen ein "
    "Kompendium entsteht. Antworte nur mit JSON."
)
NEW_QUESTION = (
    "Thema: {topic}\n\n"
    "Das Thema kann ein einzelner Begriff sein, eine Gruppe (etwa „deutsche Dichter“) oder die Verbindung zweier "
    "Themen (etwa „Klimawandel und Landwirtschaft“). Nenne die Artikel, die es zusammen abdecken:\n"
    "- zuerst den Übersichtsartikel, der das Thema als Ganzes behandelt - bei einer Gruppe die Epoche, Gattung oder "
    "den Oberbegriff, keine Liste;\n"
    "- dann bis zu {count} Artikel zu den wichtigsten Vertretern, Teilen oder Aspekten des Themas.\n"
    "Nenne nur Titel, die es in der deutschsprachigen Wikipedia gibt, in ihrer genauen Schreibweise.\n"
    'Antworte so: {{"uebersicht": "<Titel>", "artikel": ["<Titel>", ...]}}'
)

out_path, gold_paths = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]
service = cli_service(ZIMS)
if service.llm is None:
    raise SystemExit("LLM_ENABLED did not reach the settings")
client = service.llm.client
wiki = service.registry.primary_archive
assert wiki is not None


def looked_up(labels: list[str]) -> list[str]:
    """As M37: directly with redirects, then the old spelling variants; no disambiguation page."""
    titles: list[str] = []
    for label in labels:
        for candidate in [label, *variations(label)]:
            article = wiki.read_article(candidate)
            if article is not None:
                if not wiki.parse(article).is_disambiguation and article.title not in titles:
                    titles.append(article.title)
                break
    return titles


def accepted(titles: list[str]) -> list[str]:
    found = list(titles)
    for title in titles:
        article = wiki.read_article(title)
        if article is not None and article.title not in found:
            found.append(article.title)
    return found


def ask_n(topic: str) -> dict[str, Any]:
    question = NEW_QUESTION.format(topic=topic, count=MAX_NAMED)
    started = time.perf_counter()
    result = client.chat(
        [{"role": "system", "content": NEW_SYSTEM}, {"role": "user", "content": question}],
        max_output_tokens=client.completion_limit(600),
    )
    answer = read_object(result.text) or {}
    overview = str(answer.get("uebersicht") or "").strip()
    named = [str(t).strip() for t in answer.get("artikel") or [] if str(t).strip()][:MAX_NAMED]
    return {
        "uebersicht": overview,
        "genannt": named,
        "gefunden": looked_up([overview, *named] if overview else named),
        "tokens": result.total_tokens,
        "sekunden": round(time.perf_counter() - started, 2),
    }


rows: list[dict[str, Any]] = []
total = 0
for gold_path in gold_paths:
    for item in yaml.safe_load(gold_path.read_text(encoding="utf-8"))["anfragen"]:
        total += 1
        query, expected = item["anfrage"], accepted(item["erwartet"])
        rules = choose_main_article(service.registry, service.subjects, query, [], job=None)
        title, method = rules.resolution.title or "", rules.resolution.method
        if method not in GUESSED and not title.startswith("Liste "):
            continue
        asked = ask_n(rules.normalized.topic)
        new = asked["gefunden"][0] if asked["gefunden"] else title
        row = {
            "anfrage": query,
            "art": item["art"],
            "erwartet": item["erwartet"],
            "regeln": {"titel": title, "methode": method, "richtig": title in expected},
            "n": {**asked, "hauptartikel": new, "richtig": new in expected},
        }
        rows.append(row)
        print(f"{query:36s} Regeln: {title} ({method})  N: {new}  {'richtig' if new in expected else 'FALSCH'}")

out_path.write_text(json.dumps({"anfragen": total, "n_ersetzt": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
right = sum(r["n"]["richtig"] for r in rows)
print(f"{len(rows)} von {total} Anfragen lösen N aus; mit N richtig: {right}, mit den Regeln: "
      f"{sum(r['regeln']['richtig'] for r in rows)}")  # fmt: skip
