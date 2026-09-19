"""Legacy linker and utils (PLAN.md 8.1, D14): entities from the archives, splitting and synonyms without an LLM."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.knowledge.chunking import split_text
from app.main import create_app
from tests.conftest import make_settings

TEXT = (
    "Die Optik ist ein Teilgebiet der Physik. Sie beschreibt das Licht und seine Ausbreitung. "
    "Linsen bündeln Licht. Brillen korrigieren Fehlsichtigkeit."
)


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("v1utils") / "state")
    return TestClient(create_app(settings))


def test_the_linker_answers_entities_from_the_archives(client: TestClient) -> None:
    response = client.post("/api/v1/linker", json={"text": "Optik"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"original_text", "entities", "relationships", "qa_pairs", "statistics"}
    assert body["original_text"] == "Optik" and body["relationships"] == [] and body["qa_pairs"] == []
    entities = body["entities"]
    assert entities and set(entities[0]) == {"entity", "details", "sources", "id"}
    first = entities[0]
    assert first["entity"] == "Optik" and first["details"] == {"typ": "TOPIC", "citation": "Optik"}
    wikipedia = first["sources"]["wikipedia"]
    assert set(wikipedia) == {
        "status",
        "label_de",
        "label_en",
        "url_de",
        "url_en",
        "extract",
        "categories",
        "internal_links",
        "wikidata_id",
        "thumbnail_url",
        "geo_lat",
        "geo_lon",
        "infobox_type",
        "dbpedia_uri",
        "source",
        "needs_fallback",
        "fallback_attempts",
    }
    assert wikipedia["status"] == "found" and wikipedia["url_de"].startswith("http")
    assert wikipedia["extract"] and wikipedia["source"] == "zim"
    assert first["id"] == first["id"] and first["id"]  # a stable id, not a random one per request
    statistics = body["statistics"]
    assert statistics["total_entities"] == len(entities) and statistics["total_relationships"] == 0
    assert statistics["types_distribution"]["TOPIC"] >= 1  # the article and its twin in another archive
    assert statistics["linked"]["wikipedia"] == {"count": len(entities), "percent": 100.0}
    assert set(statistics["top10"]) == {"wikipedia_categories", "wikipedia_internal_links"}


def test_extract_names_the_article_itself_and_generate_adds_its_neighbours(client: TestClient) -> None:
    extract = client.post("/api/v1/linker", json={"text": "Optik", "config": {"MODE": "extract"}}).json()
    generate = client.post("/api/v1/linker", json={"text": "Optik", "config": {"MODE": "generate"}}).json()
    assert 0 < len(extract["entities"]) <= len(generate["entities"])
    assert {e["details"]["typ"] for e in extract["entities"]} == {"TOPIC"}
    assert "RELATED" in {e["details"]["typ"] for e in generate["entities"]}
    assert len(client.post("/api/v1/linker", json={"text": "Optik"}).json()["entities"]) == len(generate["entities"])


def test_the_linker_says_nothing_found_instead_of_failing(client: TestClient) -> None:
    body = client.post("/api/v1/linker", json={"text": "Xyzzyplomb"}).json()
    assert body["entities"] == [] and body["statistics"]["total_entities"] == 0
    assert body["statistics"]["linked"]["wikipedia"] == {"count": 0, "percent": 0}
    assert client.post("/api/v1/linker", json={"text": "   "}).status_code == 400
    assert client.post("/api/v1/linker", json={}).status_code == 422


def test_split_honours_the_requested_chunk_size(client: TestClient) -> None:
    payload = {"text": TEXT, "chunk_size": 60, "overlap": 0}
    chunks = client.post("/api/v1/utils/split", json=payload).json()["chunks"]
    assert chunks and all(len(chunk) <= 60 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == TEXT.replace(" ", "")
    small = {"text": TEXT, "chunk_size": 40, "overlap": 10, "split_by": "char"}
    by_char = client.post("/api/v1/utils/split", json=small).json()
    assert all(len(chunk) <= 40 for chunk in by_char["chunks"])
    assert client.post("/api/v1/utils/split", json={"text": " ", "chunk_size": 50}).status_code == 400
    assert client.post("/api/v1/utils/split", json={"text": TEXT, "chunk_size": 50, "overlap": 60}).status_code == 400
    assert client.post("/api/v1/utils/split", json={"text": TEXT, "chunk_size": 5}).status_code == 422


def test_split_keeps_sentences_together_and_repeats_the_overlap() -> None:
    chunks = split_text(TEXT, chunk_size=80, overlap=40, split_by="sentence")
    assert chunks == [
        "Die Optik ist ein Teilgebiet der Physik.",
        "Sie beschreibt das Licht und seine Ausbreitung. Linsen bündeln Licht.",
        "Linsen bündeln Licht. Brillen korrigieren Fehlsichtigkeit.",  # the overlap repeats a whole sentence
    ]
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert split_text("", chunk_size=50, overlap=0, split_by="sentence") == []


def test_synonyms_come_from_the_archives(client: TestClient) -> None:
    response = client.post("/api/v1/utils/synonyms", json={"word": "Optik", "max_synonyms": 5})
    assert response.status_code == 200, response.text
    synonyms = response.json()["synonyms"]
    assert isinstance(synonyms, list) and len(synonyms) <= 5
    assert "Optik" not in synonyms
    unknown = client.post("/api/v1/utils/synonyms", json={"word": "Xyzzyplomb"}).json()
    assert unknown["synonyms"] == []
    assert client.post("/api/v1/utils/synonyms", json={"word": ""}).status_code == 422
