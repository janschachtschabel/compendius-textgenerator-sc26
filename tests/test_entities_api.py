"""POST /api/v2/entities (docs/umbau.md, U3): the two layers answer even when the other one is missing.

The point of the split: a service without the Wikipedia archive still returns names, and a service without the
spaCy model still returns the terms that have an article. Neither silence is acceptable, and the answer says
which way produced what.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.conftest import make_settings

TEXT = "Ernst Abbe entwickelte in Jena das Lichtmikroskop und die Geometrische Optik."


@dataclass
class FakeEnt:
    text: str
    start_char: int
    end_char: int
    label_: str


@dataclass
class FakeDoc:
    ents: list[FakeEnt]


def fake_nlp(text: str) -> FakeDoc:
    return FakeDoc(ents=[FakeEnt("Ernst Abbe", 0, 10, "PER"), FakeEnt("Jena", 26, 30, "LOC")])


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def without_archives(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """A service that has no archive at all: only the model can say anything."""
    settings = make_settings([], tmp_path_factory.mktemp("leer") / "state")
    return TestClient(create_app(settings))


def with_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.v2.entities.load_spacy", lambda path: fake_nlp)


def test_without_a_model_the_terms_of_the_archives_still_come(client: TestClient) -> None:
    body = client.post("/api/v2/entities", json={"text": TEXT}).json()
    assert body["methods"] == ["dictionary"], "no spaCy model is configured in the tests"
    assert {entity["text"] for entity in body["entities"]} >= {"Lichtmikroskop", "Geometrische Optik"}
    assert all(entity["source"] == "dictionary" for entity in body["entities"])


def test_without_archives_the_names_still_come(without_archives: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with_model(monkeypatch)
    body = without_archives.post("/api/v2/entities", json={"text": TEXT}).json()
    assert body["archives"] == []
    assert [entity["text"] for entity in body["entities"]] == ["Ernst Abbe", "Jena"]
    assert all(entity["linked"] is False and entity["article"] is None for entity in body["entities"])


def test_both_ways_together_and_the_article_behind_a_name(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with_model(monkeypatch)
    body = client.post("/api/v2/entities", json={"text": TEXT}).json()
    assert body["methods"] == ["ner", "dictionary"]
    by_text = {entity["text"]: entity for entity in body["entities"]}
    assert by_text["Ernst Abbe"]["source"] == "ner" and by_text["Ernst Abbe"]["kind"] == "PER"
    abbe = by_text["Ernst Abbe"]["article"]
    assert abbe["title"] == "Ernst Abbe" and abbe["archive"] and abbe["url"].startswith("http")
    assert abbe["kind"] == "Person", "the kind comes from the lead of the article"
    assert by_text["Jena"]["linked"] is False, "no article, so nothing to link"
    assert by_text["Lichtmikroskop"]["source"] == "dictionary"


def test_linking_can_be_turned_off(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with_model(monkeypatch)
    body = client.post("/api/v2/entities", json={"text": TEXT, "link": False}).json()
    assert body["entities"] and all(entity["article"] is None for entity in body["entities"])


def test_one_way_can_be_asked_alone(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with_model(monkeypatch)
    body = client.post("/api/v2/entities", json={"text": TEXT, "methods": ["ner"]}).json()
    assert body["methods"] == ["ner"]
    assert all(entity["source"] == "ner" for entity in body["entities"])


def test_an_unknown_archive_is_refused(client: TestClient) -> None:
    response = client.post("/api/v2/entities", json={"text": TEXT, "archives": ["gibt_es_nicht"]})
    assert response.status_code == 404
    assert "gibt_es_nicht" in str(response.json()["detail"])


def test_a_text_beyond_the_bound_is_refused(client: TestClient) -> None:
    assert client.post("/api/v2/entities", json={"text": "x" * 50_001}).status_code == 422
    assert client.post("/api/v2/entities", json={"text": ""}).status_code == 422


def test_the_number_of_entities_is_capped(client: TestClient) -> None:
    body = client.post("/api/v2/entities", json={"text": TEXT, "max_entities": 1}).json()
    assert len(body["entities"]) == 1


def test_health_says_whether_the_model_is_there(client: TestClient, sample_zims: dict[str, Path]) -> None:
    entities = client.get("/health").json()["components"]["entities"]
    assert entities == {"ner": False, "model": ""}
