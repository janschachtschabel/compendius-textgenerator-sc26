"""POST /api/v2/entities in the four profiles (D62): the ways measured in M36, each where it pays.

llm-free keeps the rules - spaCy and the dictionary of titles, F1 0.38 on the texts of 40 materials. balanced and the
best-quality profiles let the LLM name the entities with the title of their article (0.78). The check of the links
(link_check llm) raised the precision to 0.94 but cost a third of the fitting entities, F1 0.76, so no profile sets
it; a caller who wants it says so. A switch the request sets wins, as everywhere; on a server without an
LLM what needs one is a 503, and while the b-api is away the rules take over and the answer says why.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.conftest import make_settings
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

TEXT = "Ernst Abbe entwickelte in Jena das Lichtmikroskop und die Geometrische Optik."
NAMED = {
    "entitaeten": [
        {"text": "Ernst Abbe", "titel": "Ernst Abbe"},
        {"text": "Jena", "titel": "Jena"},  # the sample archive has no article on Jena
        {"text": "Lichtmikroskop", "titel": "Lichtmikroskop"},
        {"text": "Geometrische Optik", "titel": "Geometrische Optik"},
    ]
}
GRADES = {"a1": 2, "a2": 1, "a3": 2}  # Ernst Abbe, Lichtmikroskop, Geometrische Optik: the linked ones in text order


def model(body: dict[str, Any]) -> str:
    """Names the entities, or grades the links when it is asked to check."""
    asked = body["messages"][-1]["content"]
    return json.dumps(GRADES if "Bewerte jede Verknüpfung" in asked else NAMED)


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def with_llm(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, FakeBApi]]:
    fake = FakeBApi(model)
    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(fake))  # type: ignore[attr-defined]
    yield client, fake


def post(client: TestClient, **fields: Any) -> dict[str, Any]:
    response = client.post("/api/v2/entities", json={"text": TEXT, **fields})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def texts(body: dict[str, Any]) -> list[str]:
    return [entity["text"] for entity in body["entities"]]


def test_llm_free_finds_with_the_rules_alone_even_where_an_llm_is_configured(
    with_llm: tuple[TestClient, FakeBApi],
) -> None:
    client, fake = with_llm
    body = post(client, preset="llm-free")
    assert body["methods"] == ["dictionary"], "ner and dictionary, and the tests carry no spaCy model"
    assert body["llm"] is None and fake.bodies == []


def test_balanced_lets_the_llm_name_the_entities_with_their_article(with_llm: tuple[TestClient, FakeBApi]) -> None:
    client, fake = with_llm
    body = post(client, preset="balanced")
    assert body["methods"] == ["llm"]
    assert texts(body) == ["Ernst Abbe", "Lichtmikroskop", "Geometrische Optik"], "a name without an article goes"
    abbe = body["entities"][0]
    assert abbe["source"] == "llm" and abbe["kind"] == "" and TEXT[abbe["start"] : abbe["end"]] == "Ernst Abbe"
    assert abbe["article"]["kind"] == "Person" and abbe["article"]["ids"]["gnd"] == "118646419"
    assert body["llm"] == {
        "named": 4,
        "checked": 0,
        "dropped": [],
        "calls": 1,
        "total_tokens": 24,
        "model": "gpt-5.6-luna",
        "prompts": ["entity_extraction@v1"],
        "fallback": None,
    }
    assert len(fake.bodies) == 1, "balanced does not check"


@pytest.mark.parametrize("preset", ["best-quality", "best-quality-generated", "best-coverage-generated"])
def test_the_best_quality_profiles_name_as_balanced_does(with_llm: tuple[TestClient, FakeBApi], preset: str) -> None:
    client, fake = with_llm
    body = post(client, preset=preset)
    assert body["methods"] == ["llm"] and texts(body) == ["Ernst Abbe", "Lichtmikroskop", "Geometrische Optik"]
    assert len(fake.bodies) == 1 and body["llm"]["checked"] == 0, "no profile checks the links"


def test_asked_for_the_check_keeps_only_what_it_grades_2(with_llm: tuple[TestClient, FakeBApi]) -> None:
    client, fake = with_llm
    body = post(client, preset="best-quality", link_check="llm")
    assert texts(body) == ["Ernst Abbe", "Geometrische Optik"]
    assert body["llm"]["checked"] == 3 and body["llm"]["dropped"] == ["Lichtmikroskop"]
    assert body["llm"]["prompts"] == ["entity_extraction@v1", "entity_check@v1"] and body["llm"]["calls"] == 2
    asked = fake.bodies[1]["messages"][-1]["content"]
    assert "a1: „Ernst Abbe“ → Ernst Abbe: " in asked and "a3: „Geometrische Optik“ → Geometrische Optik: " in asked


def test_a_switch_the_request_sets_wins_over_the_profile(with_llm: tuple[TestClient, FakeBApi]) -> None:
    client, fake = with_llm
    body = post(client, preset="best-quality", methods=["dictionary"], link_check="rule-based")
    assert body["methods"] == ["dictionary"] and body["llm"] is None and fake.bodies == []


def test_the_check_takes_the_links_of_the_rules_too(with_llm: tuple[TestClient, FakeBApi]) -> None:
    client, _ = with_llm
    body = post(client, preset="llm-free", link_check="llm")
    assert body["methods"] == ["dictionary"] and texts(body) == ["Ernst Abbe", "Geometrische Optik"]


def test_while_the_llm_is_away_the_rules_take_its_place_and_say_why(
    with_llm: tuple[TestClient, FakeBApi], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fake = with_llm
    reason = "LLM nicht verfügbar (Modell fehlt); Regelmodus verwendet"
    monkeypatch.setattr(client.app.state.service, "llm_unavailable", lambda: reason)  # type: ignore[attr-defined]
    body = post(client, preset="best-quality", link_check="llm")
    assert body["methods"] == ["dictionary"] and fake.bodies == []
    assert all(entity["source"] == "dictionary" for entity in body["entities"])
    assert reason in body["note"] and body["llm"]["fallback"] == reason and body["llm"]["calls"] == 0


def test_an_answer_that_cannot_be_read_leaves_the_rules_to_decide(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(FakeBApi(lambda body: "nichts")))  # type: ignore[attr-defined]
    body = post(client, preset="balanced")
    assert body["methods"] == ["dictionary"] and texts(body) == ["Ernst Abbe", "Lichtmikroskop", "Geometrische Optik"]
    assert body["llm"]["fallback"] == "Antwort nicht lesbar" and body["llm"]["calls"] == 1
    assert "Antwort nicht lesbar" in body["note"]


def test_without_linking_the_names_of_the_llm_come_unchecked(with_llm: tuple[TestClient, FakeBApi]) -> None:
    client, fake = with_llm
    body = post(client, preset="balanced", link=False)
    assert texts(body) == ["Ernst Abbe", "Jena", "Lichtmikroskop", "Geometrische Optik"]
    assert all(entity["article"] is None for entity in body["entities"])
    assert len(fake.bodies) == 1
    assert "llm" in body["note"] and "ungeprüft" in body["note"]


def test_llm_ways_on_a_server_without_an_llm_are_a_503(client: TestClient) -> None:
    for fields in ({"methods": ["llm"]}, {"link_check": "llm"}, {"preset": "balanced"}):
        response = client.post("/api/v2/entities", json={"text": TEXT, **fields})
        assert response.status_code == 503, fields
        assert "llm-free" in response.json()["detail"]


def test_a_check_of_the_links_without_linking_is_refused(client: TestClient) -> None:
    response = client.post("/api/v2/entities", json={"text": TEXT, "link": False, "link_check": "llm"})
    assert response.status_code == 422 and "prüft die Verknüpfungen" in response.text


def test_without_a_preset_and_without_an_llm_the_rules_recognise(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """Shipped, PRESET_DEFAULT is balanced, and balanced names the LLM; without one a bare request runs llm-free (D68).
    A request that asks for the LLM itself is still refused, with what to do."""
    client = TestClient(create_app(make_settings(sample_zims.values(), tmp_path / "state", preset_default="balanced")))
    bare = client.post("/api/v2/entities", json={"text": TEXT})
    assert bare.status_code == 200 and bare.json()["methods"] and "llm" not in bare.json()["methods"]
    refused = client.post("/api/v2/entities", json={"text": TEXT, "preset": "balanced"})
    assert refused.status_code == 503 and "methods=llm" in refused.json()["detail"]


# Found by the review of D62


def test_on_the_same_word_the_title_the_llm_named_wins(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """With dictionary and llm together the dictionary's "Brechung" took the place; its entry is a disambiguation
    page, so the word was gone although the LLM had named its article."""
    answer = json.dumps({"entitaeten": [{"text": "Brechung", "titel": "Brechung (Physik)"}]})
    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(FakeBApi(lambda body: answer)))  # type: ignore[attr-defined]
    body = post(client, text="Die Brechung des Lichts erklärt das Lichtmikroskop.", methods=["dictionary", "llm"])
    found = {entity["text"]: (entity["source"], entity["article"]["title"]) for entity in body["entities"]}
    assert found == {
        "Brechung": ("llm", "Brechung (Physik)"),
        "Lichts": ("dictionary", "Licht"),  # the genitive, through the Klexikon
        "Lichtmikroskop": ("dictionary", "Lichtmikroskop"),
    }


def test_a_check_answer_that_cannot_be_read_keeps_every_link_and_says_why(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable_grades(body: dict[str, Any]) -> str:
        asked = body["messages"][-1]["content"]
        return json.dumps({"1": 2, "2": 2, "3": 2} if "Bewerte jede Verknüpfung" in asked else NAMED)

    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(FakeBApi(unreadable_grades)))  # type: ignore[attr-defined]
    body = post(client, preset="balanced", link_check="llm")
    assert texts(body) == ["Ernst Abbe", "Lichtmikroskop", "Geometrische Optik"]
    assert (
        body["llm"]["checked"] == 0
        and body["llm"]["dropped"] == []
        and body["llm"]["fallback"] == "Antwort nicht lesbar"
    )
    assert "Prüfung durch das LLM entfiel: Antwort nicht lesbar" in body["note"]


def test_the_room_for_the_names_follows_max_entities(with_llm: tuple[TestClient, FakeBApi]) -> None:
    client, fake = with_llm
    post(client, preset="balanced", max_entities=200)
    assert fake.bodies[0]["max_completion_tokens"] == 5800


def _outcome_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "app.observability.outcome"]


def test_entities_the_llm_named_leave_one_line_and_the_rules_none(
    with_llm: tuple[TestClient, FakeBApi], caplog: pytest.LogCaptureFixture
) -> None:
    """Logging review of 2026-10-08 (H2): what the LLM did for the entities stood only in the answer."""
    client, _ = with_llm
    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        post(client, preset="llm-free")
        assert _outcome_lines(caplog) == []
        post(client, preset="balanced")

    [record] = _outcome_lines(caplog)
    assert record.levelno == logging.INFO
    assert record.getMessage().startswith("entities: balanced, LLM naming, 1 calls, ")
    assert record.getMessage().endswith(" tokens, fallbacks none")


def test_entities_the_llm_was_away_for_are_a_warning_that_names_the_reason(
    with_llm: tuple[TestClient, FakeBApi], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The breaker logs its change once; this line ties the request to it."""
    client, _ = with_llm
    reason = "LLM nicht verfügbar (Modell fehlt); Regelmodus verwendet"
    monkeypatch.setattr(client.app.state.service, "llm_unavailable", lambda: reason)  # type: ignore[attr-defined]

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        post(client, preset="best-quality", link_check="llm")

    [record] = _outcome_lines(caplog)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        "entities: best-quality, LLM none, 0 calls, 0 tokens, fallbacks naming unavailable=1, "
        f"link_check unavailable=1; {reason}"
    )


def test_names_and_a_check_the_budget_left_no_room_for_are_a_warning(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Time or budget cut LLM work: the rules found the entities, every link stayed."""
    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(FakeBApi(model), per_request=10))  # type: ignore[attr-defined]

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        post(client, preset="balanced", link_check="llm")

    [record] = _outcome_lines(caplog)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        "entities: balanced, LLM none, 0 calls, 0 tokens, fallbacks naming budget=1, link_check budget=1"
    )
