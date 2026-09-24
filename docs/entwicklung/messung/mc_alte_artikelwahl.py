"""The article choice of the old service (v0.2.0) on the gold of M9, in the flow of the new one (M17).

The old service chose no main article. Its linker asked an LLM for up to ten entities "with exact Wikipedia
article titles" (mode generate, educational mode on, alterCode/compendious/app/core/openai_wrapper.py) and looked
every title up live: directly with redirects, then with simple spelling variants, then with three LLM synonyms. The
leads of what it found were the sources of the text. Here the same prompt, word for word, goes to the model of the
new service (in M17 gpt-5.6-luna instead of gpt-4.1-mini, no temperature), and the titles are looked up in the Wikipedia
archive the new service reads, directly and with the old variants; the synonym step is left out and counted instead.

Per query of the three gold sets in eval/artikelwahl:
- first: the article behind the first entity is an accepted main article;
- among: any article behind the entities is one;
- for comparison, the rules of the new service in the same run (article_choice=rule-based): the main article, and
  whether an accepted article is anywhere in the corpus they build.

Also per found article: disambiguation page or not, and the GND number of its Normdaten block, if it has one.
Writes titles and numbers, no article text. A hard token limit stops the run.

Usage (project venv, from the project root: the service reads config/ relative to it, and without
config/subjects.yaml the rules lose the subject context - 79 instead of 86):
python docs/entwicklung/messung/mc_alte_artikelwahl.py <out.json> <token_limit> [<model>]
Without <model> the service's own model answers; with gpt-4.1-mini the old service's model does, at its
temperature 0.7 - the way the old service ran in M2. gpt-4.1-mini is outdated and dearer; it serves this
replay of the old service only and is used nowhere else (D44).
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from alter_linker import MAX_ENTITIES, SYSTEM, labels_of, user_prompt, variations

from app.cli_common import cli_service
from app.domain.requests import GenerateRequest
from app.llm.client import BApiClient, LlmError
from app.service import TopicNotFoundError

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
EVAL = Path(__file__).resolve().parents[3] / "eval" / "artikelwahl"
GOLD = ["hauptartikel.yaml", "hauptartikel_validierung.yaml", "hauptartikel_test.yaml"]
PARALLEL = 4


NORMDATEN_RE = re.compile(r"Normdaten(?:&nbsp;|\s)\(([^)]+)\)")
GND_RE = re.compile(r"d-nb\.info/gnd/([0-9X-]+)")


def normdaten(html: str) -> tuple[str | None, str | None]:
    """The kind and the GND number of the Normdaten block, read only inside that block."""
    start = html.find('id="normdaten"')
    if start < 0:
        return None, None
    block = html[start : start + 3000]
    kind, gnd = NORMDATEN_RE.search(block), GND_RE.search(block)
    return (kind.group(1) if kind else None), (gnd.group(1) if gnd else None)


out_path, token_limit = Path(sys.argv[1]), int(sys.argv[2])
OLD_MODEL = sys.argv[3] if len(sys.argv) > 3 else None
service = cli_service(ZIMS)
assert service.llm is not None, "LLM_ENABLED did not reach the settings"
client = service.llm.client
if OLD_MODEL:  # the old service's model and temperature; the key stays in the settings
    settings = service.settings
    client = BApiClient(
        client.base_url,
        settings.b_api_key,
        provider=settings.b_api_provider,
        model=OLD_MODEL,
        temperature=0.7,
        max_concurrency=PARALLEL,
    )
wiki = service.registry.primary_archive
assert wiki is not None
spent = {"tokens": 0, "calls": 0, "failed": 0, "stopped": False}
lock = threading.Lock()


def lookup(label: str) -> dict:
    """Directly with redirects, then the old variants; the synonym step of the old service is not run."""
    for way, candidate in [("direkt", label)] + [("variante", v) for v in variations(label)]:
        article = wiki.read(candidate)
        if article is None:
            continue
        kind, gnd = normdaten(article.html)
        return {
            "label": label,
            "titel": article.title,
            "weg": way,
            "begriffsklaerung": wiki.parse(article).is_disambiguation,
            "normdaten": kind,
            "gnd": gnd,
        }
    return {"label": label, "titel": None, "weg": "nicht gefunden"}


def ask(query: str) -> dict:
    with lock:
        if spent["tokens"] >= token_limit:
            spent["stopped"] = True
            return {"skipped": True}
    started = time.perf_counter()
    try:
        result = client.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_prompt(query)}],
            max_output_tokens=client.completion_limit(800),  # the old max_tokens
        )
    except LlmError as exc:
        with lock:
            spent["failed"] += 1
        return {"error": str(exc)[:200]}
    with lock:
        spent["tokens"] += result.total_tokens
        spent["calls"] += 1
    seconds = round(time.perf_counter() - started, 2)
    try:
        labels = labels_of(result.text)[:MAX_ENTITIES]
    except (ValueError, AttributeError) as exc:
        return {"error": f"kein JSON: {exc}"[:200], "tokens": result.total_tokens, "s": seconds}
    return {"labels": labels, "tokens": result.total_tokens, "s": seconds, "finish_reason": result.finish_reason}


def accepted(titles: list[str]) -> list[str]:
    """The gold titles and the articles their redirects lead to, as M9 counts them."""
    found = list(titles)
    for title in titles:
        article = wiki.read(title)
        if article is not None and article.title not in found:
            found.append(article.title)
    return found


def rules(query: str) -> tuple[str | None, list[str]]:
    """The main article and the Wikipedia titles of the corpus the rules build (no LLM)."""
    request = GenerateRequest(topic=query, parts=["world"], article_choice="rule-based")
    try:
        prepared = service.prepare(request)
    except TopicNotFoundError:
        return None, []
    picked = service.registry.build_corpus(
        prepared.resolution, slots=prepared.template.content_slots(), max_articles=service.settings.corpus_max_articles
    )
    return prepared.resolution.title, [s.title for s in picked if s.project == "wikipedia"]


queries = [
    (name, entry["anfrage"], entry["erwartet"])
    for name in GOLD
    for entry in yaml.safe_load((EVAL / name).read_text(encoding="utf-8"))["anfragen"]
]
with ThreadPoolExecutor(max_workers=PARALLEL) as executor:
    answers = list(executor.map(ask, [query for _, query, _ in queries]))

rows = []
for (gold_set, query, expected), answer in zip(queries, answers, strict=True):
    ok = accepted(expected)
    found = [lookup(label) for label in answer.get("labels", [])]
    main, corpus = rules(query)
    rows.append(
        {
            "goldsatz": gold_set,
            "anfrage": query,
            "akzeptiert": ok,
            "alt": {**{k: v for k, v in answer.items() if k != "labels"}, "artikel": found},
            "alt_erster": bool(found) and found[0]["titel"] in ok,
            "alt_darunter": any(f["titel"] in ok for f in found),
            "regeln": main,
            "regeln_richtig": main in ok,
            "regeln_korpus": any(t in ok for t in corpus),
        }
    )

out_path.write_text(
    json.dumps({"modell": client.model, "spent": spent, "anfragen": rows}, ensure_ascii=False, indent=1),
    encoding="utf-8",
)

asked = [r for r in rows if "finish_reason" in r["alt"]]  # answered with a list of entities
articles = [a for r in asked for a in r["alt"]["artikel"]]
hits = [a for a in articles if a["titel"]]
print(
    f"Anfragen {len(rows)}, beantwortet {len(asked)}; Aufrufe {spent['calls']}, fehlgeschlagen {spent['failed']}, "
    f"Tokens {spent['tokens']}, abgebrochen {spent['stopped']}"
)
print(
    f"Alt: Hauptartikel an erster Stelle {sum(r['alt_erster'] for r in rows)}, "
    f"unter den Artikeln {sum(r['alt_darunter'] for r in rows)} von {len(rows)}"
)
print(
    f"Regeln: Hauptartikel {sum(r['regeln_richtig'] for r in rows)}, im Korpus {sum(r['regeln_korpus'] for r in rows)}"
)
print(
    f"Alt: Begriffe {len(articles)}, gefunden {len(hits)} (Varianten {sum(a['weg'] == 'variante' for a in hits)}), "
    f"Begriffsklärungen {sum(a['begriffsklaerung'] for a in hits)}, mit GND {sum(bool(a['gnd']) for a in hits)}"
)
if asked:
    print(
        f"Alt je Anfrage: Tokens Median {statistics.median(r['alt']['tokens'] for r in asked)}, "
        f"Zeit Median {statistics.median(r['alt']['s'] for r in asked):.2f} s, "
        f"90. Perzentil {statistics.quantiles([r['alt']['s'] for r in asked], n=10)[-1]:.2f} s"
    )
