"""The LLM ways of /entities (D62, M36): the model names the entities of a text with the title of their article, and
it grades the links.

Measured on the texts of 40 materials, naming doubled F1 against the rules (0.78 instead of 0.38), and every word it
named stood in the text, so an entity keeps its place as the rules' do. Keeping only what the check graded 2 raised
the precision to 0.91. These tests hold where a named word lands, what counts as an answer, and that a missing
answer is said instead of passing for an empty result.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.knowledge.entities_llm import UNREADABLE, EntitiesLlmReport, EntityLlmJob, Link, grade_links, named_mentions
from app.llm.budget import TokenBudget
from app.llm.client import BApiClient
from tests.test_llm_client import BASE, KEY, FakeBApi

TEXT = "Ernst Abbe entwickelte in Jena das Lichtmikroskop. Ein Lichtmikroskop vergrößert."


def job_for(fake: FakeBApi, per_request: int = 20_000) -> EntityLlmJob:
    client = BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))
    return EntityLlmJob(client, TokenBudget(per_request=per_request, daily=2_000_000).open_request())


def naming(*pairs: tuple[str, str]) -> FakeBApi:
    """A model that names these (word, title) pairs."""
    answer = json.dumps({"entitaeten": [{"text": word, "titel": title} for word, title in pairs]}, ensure_ascii=False)
    return FakeBApi(lambda body: answer)


def user_message(fake: FakeBApi, index: int = 0) -> str:
    messages: list[dict[str, Any]] = fake.bodies[index]["messages"]
    return str(messages[-1]["content"])


def test_a_named_entity_keeps_the_place_of_its_word_and_the_title_it_was_named_with() -> None:
    fake = naming(("Abbe", "Ernst Abbe"), ("Lichtmikroskop", "Lichtmikroskop"))
    report = EntitiesLlmReport()
    mentions = named_mentions(job_for(fake), TEXT, report)
    assert mentions is not None
    assert [(m.text, m.start, m.end, m.title, m.source, m.kind) for m in mentions] == [
        ("Abbe", 6, 10, "Ernst Abbe", "llm", ""),
        ("Lichtmikroskop", 35, 49, "Lichtmikroskop", "llm", ""),
    ], "the first place of a word counts"
    assert report.named == 2 and report.calls == 1 and report.prompts == ["entity_extraction@v1"]


def test_a_word_in_another_case_is_found_and_keeps_the_spelling_of_the_text() -> None:
    mentions = named_mentions(job_for(naming(("lichtmikroskop", "Lichtmikroskop"))), TEXT, EntitiesLlmReport())
    assert mentions is not None and [(m.text, m.start) for m in mentions] == [("Lichtmikroskop", 35)]


def test_a_word_stands_where_it_stands_as_a_whole_word() -> None:
    """In the M36 service run "schwefel" stood first inside "schwefelsäure" and "Sonne" inside "Sonnenuntergang":
    the entity pointed into the longer word and gave way to it when the mentions were merged."""
    text = "Stichwörter: säure, schwefelsäure, schwefel. Sonnenuntergang im Zeitraffer: sun, sonne."
    fake = naming(("schwefelsäure", "Schwefelsäure"), ("schwefel", "Schwefel"), ("Sonne", "Sonne"))
    mentions = named_mentions(job_for(fake), text, EntitiesLlmReport())
    assert mentions is not None
    assert [(m.text, text[m.start - 2 : m.start]) for m in mentions] == [
        ("schwefelsäure", ", "),
        ("schwefel", ", "),
        ("sonne", ", "),
    ], "a whole word first, in the case of the model, then in any case"


def test_a_word_that_stands_only_inside_a_longer_one_is_found_there() -> None:
    mentions = named_mentions(job_for(naming(("Sonne", "Sonne"))), "Der Sonnenuntergang.", EntitiesLlmReport())
    assert mentions is not None and [(m.text, m.start) for m in mentions] == [("Sonne", 4)]


def test_a_word_that_is_not_in_the_text_is_left_out() -> None:
    report = EntitiesLlmReport()
    mentions = named_mentions(job_for(naming(("Mikroskopie", "Mikroskopie"), ("Jena", "Jena"))), TEXT, report)
    assert mentions is not None and [m.text for m in mentions] == ["Jena"]
    assert report.named == 1, "only what stands in the text counts as named"


def test_an_empty_list_is_an_answer_and_no_list_is_none() -> None:
    assert named_mentions(job_for(naming()), TEXT, EntitiesLlmReport()) == []
    report = EntitiesLlmReport()
    assert named_mentions(job_for(FakeBApi(lambda body: "Keine Entitäten.")), TEXT, report) is None
    assert report.fallback == UNREADABLE and report.calls == 1


def test_a_call_the_budget_turns_away_is_no_answer_and_says_why() -> None:
    report = EntitiesLlmReport()
    fake = naming(("Jena", "Jena"))
    assert named_mentions(job_for(fake, per_request=50), TEXT, report) is None
    assert fake.bodies == [] and report.fallback, "no call, and the reason is kept"


def test_the_model_is_asked_with_the_prompt_measured_in_m36() -> None:
    fake = naming(("Jena", "Jena"))
    named_mentions(job_for(fake), TEXT, EntitiesLlmReport())
    system = fake.bodies[0]["messages"][0]["content"]
    assert system.startswith("Du erkennst in deutschen Texten über Unterrichtsmaterial die Entitäten")
    assert user_message(fake).startswith(f"Text:\n{TEXT}\n\nNenne die Entitäten dieses Textes")


LINKS = [
    Link("Lichtmikroskop", "Lichtmikroskop", "Ein  Lichtmikroskop\nist ein Mikroskop, " + "das vergrößert " * 20),
    Link("Woche", "Woche", "Die Woche ist eine Zeiteinheit."),
]


def grading(answer: dict[str, Any]) -> FakeBApi:
    return FakeBApi(lambda body: json.dumps(answer))


def test_the_check_grades_every_link_in_one_call() -> None:
    fake = grading({"a1": 2, "a2": "0"})
    report = EntitiesLlmReport()
    assert grade_links(job_for(fake), TEXT, LINKS, report) == [2, 0]
    lines = user_message(fake).split("\n")
    first = next(line for line in lines if line.startswith("a1: "))
    assert first.startswith("a1: „Lichtmikroskop“ → Lichtmikroskop: Ein Lichtmikroskop ist ein Mikroskop, das")
    assert len(first) == len("a1: „Lichtmikroskop“ → Lichtmikroskop: ") + 180, "the lead as the M36 check saw it"
    assert report.checked == 2 and report.calls == 1 and report.prompts == ["entity_check@v1"]


def test_a_link_the_model_did_not_grade_has_no_grade() -> None:
    assert grade_links(job_for(grading({"a1": 2})), TEXT, LINKS, EntitiesLlmReport()) == [2, None]


def test_an_unreadable_check_is_no_answer() -> None:
    report = EntitiesLlmReport()
    assert grade_links(job_for(FakeBApi(lambda body: "alles gut")), TEXT, LINKS, report) is None
    assert report.fallback == UNREADABLE


def test_both_calls_keep_their_prompt_in_the_report() -> None:
    report = EntitiesLlmReport()
    named_mentions(job_for(naming(("Jena", "Jena"))), TEXT, report)
    grade_links(job_for(grading({"a1": 2, "a2": 2})), TEXT, LINKS, report)
    assert report.prompts == ["entity_extraction@v1", "entity_check@v1"] and report.calls == 2
