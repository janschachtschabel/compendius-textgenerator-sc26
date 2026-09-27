"""Whatever the model answers, the request ends in the documented fallback to the rules, never in a 500.

The prompts carry foreign text (leads from the archives, texts of materials), they are deterministic, and the b-api
answers a repeated prompt from its cache: an answer that broke a parser broke every request on that topic for as
long as it stayed cached (audit 2026-09-27, KO-03).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob, check_hits, read_number, read_object
from app.knowledge.entities_llm import _named_pairs
from app.llm.client import BApiClient
from app.matching.llm_assignment import parse_assignment
from app.sources.lehrplan.tree import _integer
from tests.test_article_choice import answering, source
from tests.test_llm_client import BASE, KEY, MESSAGES, FakeBApi, completion
from tests.test_pipeline_llm import make_gateway

HUGE = "9" * 5000  # json.loads refuses more than 4,300 digits with a plain ValueError, not a JSONDecodeError
DEEP = "[" * 100_000 + "]" * 100_000  # json.loads gives up with a RecursionError
NO_FLOAT = "1" + "0" * 400  # a JSON integer float() cannot hold: OverflowError


@pytest.mark.parametrize("value", ["²", "①", "٣", "1234", "7.0", "-1", "", " ", True, None, 1.5, [7]])
def test_read_number_takes_nothing_but_a_plain_number(value: Any) -> None:
    # "²" and "①" are digits to str.isdigit, and int() refuses them
    assert read_number(value) is None


@pytest.mark.parametrize(("value", "number"), [(7, 7), (0, 0), ("7", 7), (" 12 ", 12), ("999", 999)])
def test_read_number_reads_an_int_or_up_to_three_ascii_digits(value: Any, number: int) -> None:
    assert read_number(value) == number


@pytest.mark.parametrize(
    "text",
    ['{"wahl": ' + HUGE + "}", '{"wahl": ' + DEEP + "}", "{", "keine Ahnung"],
    ids=["huge number", "deep nesting", "open brace", "prose"],  # pytest puts the id in an environment variable
)
def test_read_object_has_no_object_where_json_cannot_read_one(text: str) -> None:
    assert read_object(text) is None


@pytest.mark.parametrize(
    "answer",
    [
        '{"entitaeten": ' + DEEP + "}",
        '{"entitaeten": "x"} {"text": "Optik", "titel": ' + HUGE + "}",
        '{"entitaeten": "x"} {"text": "Optik", "titel": ' + DEEP + "}",
    ],
    ids=["deep list", "huge number in an entry", "deep nesting in an entry"],
)
def test_named_entities_are_unreadable_rather_than_an_error(answer: str) -> None:
    assert _named_pairs(answer) is None


@pytest.mark.parametrize(
    "text", ['{"p1": ' + DEEP + "}", '{"p1": ["definition", ' + HUGE + "]}"], ids=["deep nesting", "huge number"]
)
def test_an_assignment_json_cannot_read_is_no_assignment(text: str) -> None:
    assert parse_assignment(text) is None


def test_an_assignment_skips_a_confidence_no_float_holds() -> None:
    parsed = parse_assignment('{"p1": ["definition", ' + NO_FLOAT + '], "p2": ["systematik", 0.5]}')

    assert parsed == {"p2": ("systematik", 0.5)}


def test_a_hit_check_answering_with_a_superscript_keeps_every_hit() -> None:
    gateway = make_gateway(FakeBApi(answering('{"a1": "²", "a2": "²"}')))
    corpus = [source("Optik", "primary"), source("Kernwaffe", "search"), source("Linse (Optik)", "linked")]

    gone, report = check_hits(ArticleChoiceJob(gateway.client, gateway.open_budget()), "Optik", corpus)

    assert gone == set()
    assert report.calls == 1


def test_a_hit_check_answering_with_deep_nesting_is_unreadable() -> None:
    gateway = make_gateway(FakeBApi(answering('{"a1": ' + DEEP + "}")))
    corpus = [source("Optik", "primary"), source("Kernwaffe", "search")]

    gone, report = check_hits(ArticleChoiceJob(gateway.client, gateway.open_budget()), "Optik", corpus)

    assert gone == set() and report.fallback == UNREADABLE


def answering_raw(payload: dict[str, Any]) -> BApiClient:
    """A client whose b-api answers ``payload`` on every path, written as json.dumps writes Infinity and NaN.

    httpx refuses to write them (and FakeBApi uses it), but reads them like json.loads does."""
    body = json.dumps(payload).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    return BApiClient(BASE, KEY, provider="openai", model="gpt-6-luna", transport=transport)


def test_usage_of_infinity_is_estimated_like_a_missing_one() -> None:
    payload = completion("Eine brauchbare Antwort mit Beleg [1].")
    payload["usage"] = {"prompt_tokens": float("inf"), "completion_tokens": float("nan"), "total_tokens": 1e400}

    result = answering_raw(payload).chat(MESSAGES, max_output_tokens=10)

    assert result.prompt_tokens > 0 and result.completion_tokens > 0
    assert result.total_tokens == result.prompt_tokens + result.completion_tokens


def test_a_model_list_with_an_infinite_demand_is_still_read() -> None:
    [model] = answering_raw({"data": [{"id": "gpt-6-luna", "demand": float("inf")}]}).models()

    assert model.id == "gpt-6-luna" and model.demand is None


@pytest.mark.parametrize("value", ["²", "3.", "", None])
def test_a_position_of_mem_that_is_no_plain_number_is_none(value: str | None) -> None:
    # The same int()-after-isdigit pattern in the harvest: one such position failed the whole run
    assert _integer(value) is None
