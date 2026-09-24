"""The switches of a request show their values in /docs, each explained, and an example sets them.

A caller reads the schema in /docs, not the code: which values a switch takes, what each one does, what it costs.
Checked on 2026-09-24: ``matcher`` was a bare string there, without the list of strategies, no example used
``llm``, and ``article_choice`` appeared in no example at all.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

from app.domain.requests import MATCHERS, ArticleChoice, Enrichment, Extraction, Generation, Preset
from app.main import create_app
from app.matching.registry import STRATEGIES
from app.settings import Settings
from tests.test_docs_examples import documented_examples


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def spec(client: TestClient) -> dict[str, Any]:
    schema: dict[str, Any] = client.get("/openapi.json").json()
    return schema


def enum_of(prop: dict[str, Any]) -> list[str]:
    """The values a property allows, optional (a string or null) or not."""
    for option in [prop, *prop.get("anyOf", [])]:
        if "enum" in option:
            return list(option["enum"])
    return []


def test_the_matchers_a_request_names_are_the_registered_strategies() -> None:
    assert list(MATCHERS) == list(STRATEGIES)


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("matcher", list(MATCHERS)),
        ("article_choice", list(get_args(ArticleChoice))),
        ("extraction", list(get_args(Extraction))),
        ("generation", list(get_args(Generation))),
        ("enrichment", list(get_args(Enrichment))),
        ("preset", list(get_args(Preset))),
    ],
)
def test_every_switch_of_a_compendium_lists_and_explains_its_values(
    spec: dict[str, Any], field: str, values: list[str]
) -> None:
    prop = spec["components"]["schemas"]["GenerateRequest"]["properties"][field]
    assert enum_of(prop) == values
    unexplained = [value for value in values if value not in prop["description"]]
    assert not unexplained, f"{field}: the help text says nothing about {unexplained}"


def test_an_unknown_preset_is_a_422(client: TestClient) -> None:
    assert client.post("/api/v2/compendium", json={"topic": "Optik", "preset": "turbo"}).status_code == 422


def test_an_unknown_matcher_still_gets_the_german_answer(client: TestClient) -> None:
    # The list in /docs is documentation; the check stays the service's, with its own message
    response = client.post("/api/v2/compendium", json={"topic": "Optik", "matcher": "gibtsnicht"})
    assert response.status_code == 422 and response.json()["detail"] == "Unbekannte Matching-Strategie: gibtsnicht"


def test_an_example_sets_the_article_choice_and_the_llm_matcher(spec: dict[str, Any]) -> None:
    examples = documented_examples(spec, "/api/v2/compendium").values()
    assert any("article_choice" in body for body in examples)
    assert any(body.get("matcher") == "llm" for body in examples)


def test_an_example_names_each_preset(spec: dict[str, Any]) -> None:
    named = {body.get("preset") for body in documented_examples(spec, "/api/v2/compendium").values()}
    assert set(get_args(Preset)) <= named


def test_the_knowledge_endpoint_offers_the_article_choice(spec: dict[str, Any]) -> None:
    prop = spec["components"]["schemas"]["KnowledgeRequest"]["properties"]["article_choice"]
    assert enum_of(prop) == list(get_args(ArticleChoice))
    assert all(value in prop["description"] for value in get_args(ArticleChoice))
    preset = spec["components"]["schemas"]["KnowledgeRequest"]["properties"]["preset"]
    assert enum_of(preset) == list(get_args(Preset))
    assert any("article_choice" in body for body in documented_examples(spec, "/api/v2/knowledge").values())


def test_the_comparison_lists_the_strategies_it_takes(spec: dict[str, Any]) -> None:
    prop = spec["components"]["schemas"]["CompareRequest"]["properties"]["matchers"]
    assert enum_of(prop["items"]) == list(MATCHERS)


def test_every_strategy_says_what_it_does(client: TestClient) -> None:
    strategies = client.get("/api/v2/matching/strategies").json()
    assert [strategy["id"] for strategy in strategies] == list(STRATEGIES)
    assert all(len(strategy.get("description", "")) > 60 for strategy in strategies)
