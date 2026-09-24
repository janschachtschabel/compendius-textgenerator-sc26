"""Knowledge texts without a compendium (docs/umbau.md, U2): the articles of a topic, as they stand.

A caller who only wants the sources should not have to ask for a compendium and throw the template away. The
endpoint answers with the articles the corpus builder would use - resolved, with their sections - and it can
be limited to single archives.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.test_article_choice import rating
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_the_articles_of_a_topic_come_back_with_their_text(client: TestClient) -> None:
    body = client.post("/api/v2/knowledge", json={"topic": "Optik"}).json()
    assert body["resolution"]["title"]
    first = body["articles"][0]
    assert first["is_primary"] and first["title"] and first["url"].startswith("http")
    assert first["archive"] and first["project"]
    assert first["sections"] and any(section["text"] for section in first["sections"])
    assert body["chars"] == sum(article["chars"] for article in body["articles"])


def test_one_archive_can_be_asked_alone(client: TestClient) -> None:
    body = client.post("/api/v2/knowledge", json={"topic": "Optik", "archives": ["klexikon_de_sample"]}).json()
    assert body["archives"] == ["klexikon_de_sample"]
    assert body["articles"], "the sample topic exists in the Klexikon too"
    assert {article["archive"] for article in body["articles"]} == {"klexikon_de_sample"}


def test_an_unknown_archive_is_refused(client: TestClient) -> None:
    response = client.post("/api/v2/knowledge", json={"topic": "Optik", "archives": ["gibt_es_nicht"]})
    assert response.status_code == 404
    assert "gibt_es_nicht" in str(response.json()["detail"])


def test_an_unknown_topic_says_what_was_tried(client: TestClient) -> None:
    response = client.post("/api/v2/knowledge", json={"topic": "Xyzzy Quuxbar"})
    assert response.status_code == 404
    assert response.json()["detail"]["resolution"]["query"] == "Xyzzy Quuxbar"


def test_the_corpus_can_be_kept_small(client: TestClient) -> None:
    """max_articles bounds the extra articles; the topic and its twin in another archive are always there."""
    small = client.post("/api/v2/knowledge", json={"topic": "Optik", "max_articles": 1}).json()
    assert {article["origin"] for article in small["articles"]} <= {"primary", "same_topic"}
    wide = client.post("/api/v2/knowledge", json={"topic": "Optik", "max_articles": 12}).json()
    assert len(wide["articles"]) >= len(small["articles"])


def test_the_llm_can_drop_the_full_text_hits_that_do_not_fit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same article choice as a compendium (D35), so both answers name the same articles for a topic
    fake = FakeBApi(rating({"Augenoptiker": 0}))
    monkeypatch.setattr(client.app.state.service, "llm", make_gateway(fake, per_request=100_000))  # type: ignore[attr-defined]
    body = client.post("/api/v2/knowledge", json={"topic": "Optik", "article_choice": "llm"}).json()

    titles = [article["title"] for article in body["articles"]]
    assert "Augenoptiker" not in titles and "Lichtmikroskop" in titles
    choice = body["article_choice"]
    assert choice["used"] == "llm" and choice["hits_dropped"] == ["Augenoptiker"] and choice["tokens"] == 24


def test_the_rules_choose_unless_the_llm_is_asked_for(client: TestClient) -> None:
    assert client.post("/api/v2/knowledge", json={"topic": "Optik"}).json()["article_choice"] is None
    asked = client.post("/api/v2/knowledge", json={"topic": "Optik", "article_choice": "llm"}).json()
    assert asked["article_choice"]["used"] == "rule-based" and "nicht konfiguriert" in asked["article_choice"]["note"]


def test_the_text_is_capped_and_says_so(client: TestClient) -> None:
    full = client.post("/api/v2/knowledge", json={"topic": "Optik"}).json()
    assert not full["truncated"]
    short = client.post("/api/v2/knowledge", json={"topic": "Optik", "max_chars": 500}).json()
    assert short["truncated"] and short["chars"] <= 500 < full["chars"]
    # An article the cap left nothing of is not worth listing; truncated already says there would be more
    assert all(article["sections"] for article in short["articles"])
