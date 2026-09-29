"""The article a material is about (D47): the rules over its title and description, and the question to the LLM.

Both were measured before they were built (M21, M23 on eval/materialwahl/materialien.yaml): the ranking of the terms,
the rule that picks among them and the prompt stay as measured, and these tests pin them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob
from app.knowledge.node_article import (
    MAX_ENTITIES,
    OUTPUT_TOKENS,
    PROMPT_CHARS,
    TITLE_CHARS,
    NodeArticleReport,
    ask_topic,
    ranked_entities,
    rule_article,
)
from app.llm.budget import estimate_tokens
from app.llm.prompts import get_prompt
from app.sources.wlo.models import NodeInfo
from app.sources.zim.archive import ZimArchive, ZimArticle
from app.sources.zim.registry import ZimRegistry
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

# The system prompt of M21 S4 and M23 KL (docs/entwicklung/messung/materialwege.py), word for word: 30 of 31 materials
MEASURED_SYSTEM = (
    "Du bestimmst für ein Unterrichtsmaterial das fachliche Thema, zu dem ein Kompendium für Lehrkräfte geschrieben "
    'werden soll. Antworte ausschließlich mit einem JSON-Objekt wie {"titel": "..."}: dem genauen Titel des '
    'deutschsprachigen Wikipedia-Artikels zu diesem Thema, oder "", wenn das Material kein fachliches Thema hat. '
    "Keine Erklärungen."
)


@dataclass
class Parsed:
    is_disambiguation: bool


class FakeArchive:
    """An archive that knows only titles: every one is an article, the named ones disambiguation pages."""

    def __init__(self, titles: set[str], disambiguations: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.titles = titles | disambiguations
        self.disambiguations = disambiguations

    def has(self, title: str) -> bool:
        return title in self.titles

    def read(self, title: str) -> ZimArticle | None:
        return ZimArticle(title=title, path=title, html="") if title in self.titles else None

    def parse(self, article: ZimArticle) -> Parsed:
        return Parsed(is_disambiguation=article.title in self.disambiguations)


def archives(*fakes: FakeArchive) -> list[ZimArchive]:
    """The fakes where the rules take archives: they answer what the rules ask of one, has, read and parse."""
    return cast(list[ZimArchive], list(fakes))


def material(**changes: Any) -> NodeInfo:
    values: dict[str, Any] = {
        "node_id": "19e322f0-afa5-440f-8dc0-fca1dcde71d8",
        "kind": "material",
        "title": "Zahnrad und Riemen - Experiment:",
        "description": "Ein Versuch mit Zahnrädern.",
        "keywords": ("Zahnrad", "Riemen"),
        "subject_uris": ("http://w3id.org/openeduhub/vocabs/discipline/460",),
        "subject_labels": ("Physik",),
        "educational_contexts": ("Sekundarstufe I",),
        "url": "",
    }
    values.update(changes)
    return NodeInfo(**values)


def job_for(fake: FakeBApi, per_request: int = 100_000) -> ArticleChoiceJob:
    gateway = make_gateway(fake, per_request=per_request)
    return ArticleChoiceJob(gateway.client, gateway.open_budget())


def answering(answer: Any) -> FakeBApi:
    return FakeBApi(lambda body: answer if isinstance(answer, str) else json.dumps(answer))


# -- the terms of title and description ---------------------------------------------------------------------------
def test_the_terms_of_a_real_material_rank_title_first(registry: ZimRegistry) -> None:
    ranked = ranked_entities(
        registry.archives,
        "Stationsarbeit zur Optik",
        "An sechs Stationen untersuchen Lernende Aufbau und Funktion des Auges: Netzhaut, Pupille und Linse.",
        ["Auge", "Linse", "Stationenlernen"],
    )
    assert ranked == ["Optik", "Linse"], "3 for the title, 1 per mention in the description, 2 more as a keyword"


def test_a_keyword_lifts_a_term_of_the_description_above_one_mentioned_twice() -> None:
    archive = FakeArchive({"Zahnrad", "Riemen", "Getriebe"})
    ranked = ranked_entities(
        archives(archive), "Versuch", "Getriebe und Riemen. Ein Getriebe hat Zahnrad und Riemen.", ["Riemen"]
    )
    assert ranked == ["Riemen", "Getriebe", "Zahnrad"]


def test_format_words_and_disambiguation_pages_are_no_terms() -> None:
    archive = FakeArchive({"Experiment", "Zahnrad"}, disambiguations={"Riemen"})
    assert ranked_entities(archives(archive), "Zahnrad und Riemen - Experiment:", "", []) == ["Zahnrad"]


def test_at_most_ten_terms_count() -> None:
    titles = [f"Begriff{number}" for number in range(15)]
    ranked = ranked_entities(archives(FakeArchive(set(titles))), "Material", " ".join(titles), [])
    assert ranked == titles[:MAX_ENTITIES]


# -- the rule of M23 ------------------------------------------------------------------------------------------------
def test_the_title_counts_when_its_article_is_among_the_terms() -> None:
    assert rule_article("Optik", ["Optik", "Linse"], "Stationsarbeit zur Optik") == "Optik"


def test_else_the_first_term_counts_when_the_title_names_it() -> None:
    assert rule_article("Rad", ["Zahnrad", "École"], "Zahnrad und Riemen - Experiment:") == "Zahnrad"
    assert rule_article(None, ["Zahnrad"], "Zahnrad und Riemen") == "Zahnrad"


def test_else_there_is_no_article() -> None:
    assert rule_article("Rad", ["Netzhaut", "Zahnrad"], "Zahnrad und Riemen") is None, "only the first term is asked"
    assert rule_article(None, [], "Klassenarbeit Nr. 3") is None


# -- the question to the LLM ----------------------------------------------------------------------------------------
def test_the_model_is_asked_with_the_prompt_of_m21() -> None:
    assert get_prompt("node_topic").system == MEASURED_SYSTEM
    fake = answering({"titel": "Getriebe"})
    report = NodeArticleReport()
    assert ask_topic(job_for(fake), material(), report) == ("Getriebe", "")
    system, user = fake.bodies[0]["messages"]
    assert system["content"] == MEASURED_SYSTEM
    assert user["content"] == (
        "Titel: Zahnrad und Riemen - Experiment:\nFächer: Physik\nSchlagwörter: Zahnrad, Riemen\n"
        "Beschreibung: Ein Versuch mit Zahnrädern.\n\nGib das JSON-Objekt zurück."
    )
    assert report.way == "llm" and report.named == "Getriebe" and report.fallback is None
    assert report.calls == 1 and report.prompts == ["node_topic@v1"] and report.total_tokens > 0


def test_missing_subjects_and_keywords_are_named_and_a_long_description_is_cut() -> None:
    fake = answering({"titel": "Getriebe"})
    ask_topic(job_for(fake), material(subject_labels=(), keywords=(), description="x" * 2000), NodeArticleReport())
    user = fake.bodies[0]["messages"][1]["content"]
    assert "Fächer: keine\nSchlagwörter: keine\n" in user
    assert f"Beschreibung: {'x' * PROMPT_CHARS}\n\n" in user


def test_a_long_title_and_long_keywords_are_cut_as_the_description_is() -> None:
    """Title and keywords went into the prompt uncut, only the description was cut (audit 2026-09-29, L5)."""
    fake = answering({"titel": "Getriebe"})
    keywords = tuple(f"Schlagwort{number:05d}" for number in range(1_200))  # 20,398 characters

    ask_topic(job_for(fake), material(title="T" * 1_000, keywords=keywords), NodeArticleReport())

    user = fake.bodies[0]["messages"][1]["content"]
    lines = dict(line.split(": ", 1) for line in user.splitlines() if ": " in line)
    assert lines["Titel"] == "T" * TITLE_CHARS
    assert lines["Schlagwörter"] == ", ".join(keywords)[:PROMPT_CHARS]


def test_the_text_of_the_node_is_reserved_by_its_bytes() -> None:
    """Whoever edits a node shapes its text: reserved by the estimate alone, combining marks cost up to 4.3 times the
    tokens reserved for them (audit 2026-09-28, SE-20; 2026-09-29, L5)."""
    shaped = "".join(chr(0x300 + n % 0x70) if n % 2 else "a" for n in range(1_000))
    info = material(keywords=(shaped,))
    fake = answering({"titel": "Getriebe"})
    job = job_for(fake)
    ask_topic(job, info, NodeArticleReport())
    prompt = "".join(message["content"] for message in fake.bodies[0]["messages"])
    by_estimate = estimate_tokens(prompt) + job.client.completion_limit(OUTPUT_TOKENS)

    report = NodeArticleReport()
    assert ask_topic(job_for(fake, per_request=by_estimate), info, report) is None

    assert report.fallback is not None and "Budget" in report.fallback and len(fake.bodies) == 1


def test_an_empty_title_says_the_material_has_no_subject_topic() -> None:
    report = NodeArticleReport()
    assert ask_topic(job_for(answering({"titel": ""})), material(), report) == ("", "")
    assert report.named == "" and report.fallback is None


def test_an_unreadable_answer_or_a_skipped_call_is_no_answer() -> None:
    report = NodeArticleReport()
    assert ask_topic(job_for(answering("weiß nicht")), material(), report) is None
    assert report.fallback == UNREADABLE and report.calls == 1
    skipped = NodeArticleReport()
    assert ask_topic(job_for(answering({"titel": "Getriebe"}), per_request=10), material(), skipped) is None
    assert skipped.fallback is not None and skipped.named is None


def test_with_a_topic_the_model_hears_both_and_names_the_material_article_too() -> None:
    fake = answering({"titel": "Getriebe", "material": "Zahnrad"})
    report = NodeArticleReport()
    assert ask_topic(job_for(fake), material(), report, topic="Getriebe") == ("Getriebe", "Zahnrad")
    system, user = fake.bodies[0]["messages"]
    assert system["content"] == get_prompt("node_topic_with_topic").system
    assert user["content"].startswith("Thema der Lehrkraft: Getriebe\nTitel des Materials: Zahnrad und Riemen")
    assert report.named == "Getriebe" and report.material == "Zahnrad"
    assert report.prompts == ["node_topic_with_topic@v1"]
