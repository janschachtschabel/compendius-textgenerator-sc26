"""M37: set-like and mixed topics ("deutsche Dichter") - one main article, or several articles combined?

Jan, 2026-09-26: a complex or mixed topic such as "deutsche Dichter" probably needs several fitting articles combined,
not one main article; the old app got them from the entities its LLM generated. Four ways per topic, each through the
service's own flow for part 1 with the text verbatim:

- R: llm-free as it is - the rules choose one main article, side articles join by link and full-text search;
- B: balanced as it is - the LLM decides where the rules are unsure and drops side articles that do not fit;
- A: the old app's way - the entities its linker generates (alter_linker.py, word for word) are the corpus, the first
  one the main article, as M23 KEa did for materials;
- N: a new question - the LLM names the overview article and up to eight articles on the members, parts or aspects of
  the topic; the overview is the main article, the others join the corpus as they are.

Every article a way printed from is graded blind (2 belongs to the topic, 1 related, 0 unfit) from its title and the
beginning of its lead, by two raters; the grades live in eval/sammelthemen/, the leads only in the sheet this script
writes outside the repository. The b-api answers a prompt it has seen before from its cache: A reuses the answers of
the probe that preceded this measurement.

With --normal the same four ways run on the 20 ordinary topics of M1 (eval/artikelwahl/korpus_labels.yaml), as a
control: does N help only where one article cannot carry the topic, or everywhere?

Usage (from the project folder): python mc_sammelthemen.py <out.json> <sheet.json> [--normal]
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import yaml  # noqa: E402
from alter_linker import MAX_ENTITIES, SYSTEM, labels_of, user_prompt, variations  # noqa: E402

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import Compendium  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.knowledge.article_choice import read_object  # noqa: E402
from app.llm.client import LlmError  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
ZIMS = [str(DATA / "wikipedia_de_all_nopic_2026-01.zim"), str(DATA / "klexikon_de_all_maxi_2026-08.zim")]
# Groups of persons or things, and topics that join two subjects: none of them is one Wikipedia article's title
TOPICS = [
    "deutsche Dichter", "Dichter der Romantik", "Komponisten der Klassik", "Philosophen der Aufklärung",
    "Maler des Impressionismus", "römische Kaiser", "deutsche Bundeskanzler", "griechische Götter",
    "Planeten des Sonnensystems", "Edelgase", "Weltreligionen", "erneuerbare Energien",
    "Erfindungen der Industrialisierung", "Nobelpreisträger für Physik", "Frauen in der Wissenschaft",
    "Märchen der Brüder Grimm", "deutsche Flüsse", "Säugetiere des Waldes", "Vulkane Europas",
    "Entdecker der Neuzeit", "Klimawandel und Landwirtschaft", "Mathematik in der Musik", "Chemie im Alltag",
    "Frauen im Mittelalter", "Musik der Romantik",
]  # fmt: skip
MAX_NAMED = 8
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
ACTOR = re.compile(r"^- \*\*\[([^\]]+)\]", re.MULTILINE)

out_path, sheet_path = Path(sys.argv[1]), Path(sys.argv[2])
if "--normal" in sys.argv:
    TOPICS = list(yaml.safe_load(Path("eval/artikelwahl/korpus_labels.yaml").read_text(encoding="utf-8"))["labels"])
service = cli_service(ZIMS)
assert service.llm is not None, "LLM_ENABLED did not reach the settings"
client = service.llm.client
wiki = service.registry.primary_archive
assert wiki is not None


def looked_up(labels: list[str]) -> list[str]:
    """The articles behind the labels: directly with redirects, then the old spelling variants; no disambiguation."""
    titles: list[str] = []
    for label in labels:
        for candidate in [label, *variations(label)]:
            article = wiki.read_article(candidate)
            if article is not None:
                if not wiki.parse(article).is_disambiguation and article.title not in titles:
                    titles.append(article.title)
                break
    return titles


def entity_corpus(titles: list[str]) -> Callable[..., list[Any]]:
    """build_corpus for A and N: the named articles, the first one as main article, every paragraph kept (M23)."""

    def build(resolution: Any, slots: Any, max_articles: int, material: str | None = None) -> list[Any]:
        sources: list[Any] = []
        seen: set[str] = set()
        for title in [resolution.title, *titles]:
            article = wiki.read_article(title)
            if article is None or wiki.parse(article).is_disambiguation or article.title.lower() in seen:
                continue
            seen.add(article.title.lower())
            source = wiki.to_source(article, is_primary=not sources)
            source.origin = "primary" if not sources else "entity"
            sources.append(source)
            if len(sources) == max_articles:
                break
        return sources

    return build


def generate(request: GenerateRequest, corpus: Callable[..., list[Any]] | None = None) -> tuple[Compendium, float]:
    original = service.registry.build_corpus
    if corpus is not None:
        service.registry.build_corpus = corpus  # type: ignore[method-assign]
    started = time.perf_counter()
    try:
        return service.generate(request), round(time.perf_counter() - started, 2)
    finally:
        service.registry.build_corpus = original  # type: ignore[method-assign]


def summary(result: Compendium, sheet: dict[str, str]) -> dict[str, Any]:
    """What a way printed, per article, and who its actors are; the leads go to the sheet only."""
    by_id = {source.source_id: source for source in result.sources}
    printed: Counter[str] = Counter()
    for section in result.sections:
        for chunk_id in section.chunk_ids:
            source = by_id[chunk_id.rsplit(":c", 1)[0]]
            printed[source.title] += 1
            sheet.setdefault(source.title, source.lead[:400])
    actors = next((s.text for s in result.sections if s.slot_key == "akteure"), "")
    persons = ACTOR.findall(actors.split("#### Person", 1)[1].split("#### ", 1)[0]) if "#### Person" in actors else []
    return {
        "hauptartikel": result.resolution.title,
        "methode": result.resolution.method,
        "sicher": result.resolution.confident,
        "gedruckt": [{"titel": t, "absaetze": n} for t, n in printed.most_common()],
        "bausteine": result.audit.sections_filled,
        "personen": persons,
        "tokens_dienst": (result.audit.llm_tokens or {}).get("total", 0),
    }


def ask(messages: list[dict[str, str]], limit: int) -> tuple[str, int, float]:
    started = time.perf_counter()
    result = client.chat(messages, max_output_tokens=client.completion_limit(limit))
    return result.text, result.total_tokens, round(time.perf_counter() - started, 2)


rows: list[dict[str, Any]] = []
sheets: dict[str, dict[str, str]] = {}
for topic in TOPICS:
    sheet = sheets.setdefault(topic, {})
    ways: dict[str, Any] = {}
    for way, preset in (("R", "llm-free"), ("B", "balanced")):
        result, seconds = generate(GenerateRequest(topic=topic, parts=["world"], preset=preset))  # type: ignore[arg-type]
        ways[way] = {"sekunden": seconds, **summary(result, sheet)}

    try:
        text, tokens, seconds = ask(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_prompt(topic)}], 800
        )
        labels = labels_of(text)[:MAX_ENTITIES]
    except (LlmError, ValueError, AttributeError) as exc:
        labels, tokens, seconds = [], 0, 0.0
        print(f"   A: {str(exc)[:120]}")
    titles = looked_up(labels)
    asked = {"genannt": labels, "gefunden": titles, "tokens_frage": tokens, "sekunden_frage": seconds}
    if titles:
        request = GenerateRequest(topic=titles[0], parts=["world"], preset="llm-free")
        result, seconds = generate(request, entity_corpus(titles))
        ways["A"] = {"sekunden": seconds, **summary(result, sheet), **asked}
    else:
        ways["A"] = {"status": "keine Entitäten", **asked}

    try:
        question = NEW_QUESTION.format(topic=topic, count=MAX_NAMED)
        text, tokens, seconds = ask(
            [{"role": "system", "content": NEW_SYSTEM}, {"role": "user", "content": question}], 600
        )
        answer = read_object(text) or {}
    except LlmError as exc:
        answer, tokens, seconds = {}, 0, 0.0
        print(f"   N: {str(exc)[:120]}")
    overview = str(answer.get("uebersicht") or "").strip()
    named = [str(t).strip() for t in answer.get("artikel") or [] if str(t).strip()][:MAX_NAMED]
    titles = looked_up([overview, *named] if overview else named)
    asked = {"uebersicht": overview, "genannt": named, "gefunden": titles, "tokens_frage": tokens,
             "sekunden_frage": seconds}  # fmt: skip
    if titles:
        request = GenerateRequest(topic=titles[0], parts=["world"], preset="llm-free")
        result, seconds = generate(request, entity_corpus(titles))
        ways["N"] = {"sekunden": seconds, **summary(result, sheet), **asked}
    else:
        ways["N"] = {"status": "keine Artikel", **asked}

    rows.append({"thema": topic, "wege": ways})
    marks = "  ".join(f"{w}: {ways[w].get('hauptartikel', ways[w].get('status'))}" for w in ("R", "B", "A", "N"))
    print(f"{topic:36s} {marks}", flush=True)

out_path.write_text(json.dumps({"themen": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
sheet_path.write_text(json.dumps(sheets, ensure_ascii=False, indent=1), encoding="utf-8")
