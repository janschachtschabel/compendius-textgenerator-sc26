"""A node of an edu-sharing repository as input of the endpoints (D45), and a preview of what is read from it.

``node_id`` and ``repository`` go into compendium, knowledge, qa and entities; ``GET /api/v2/nodes/{id}`` shows the
metadata and the topic the service would derive. Nodes are read without credentials, from every repository: the
endpoints have no login, so they pass on only what is public.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.conftest import make_settings
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway
from tests.test_wlo_client import BASE, EXAM, MATERIAL, OPTIK, PRIVATE, UNKNOWN, FakeRepository, _fixture

STAGING = "https://repository.staging.openeduhub.net/edu-sharing/rest"
PRODUCTION = "https://redaktion.openeduhub.net/edu-sharing/rest"


def with_fake_repository(app: FastAPI, repo: FakeRepository | None = None) -> FastAPI:
    """The configured repository (staging by default) answers from the fixtures instead of the network."""
    client = EduSharingClient(BASE, transport=httpx.MockTransport(repo or FakeRepository()), page_size=10)
    builder = CollectionBuilder(client=client, cache=None)
    app.state.collections = builder
    app.state.service.collections = builder
    return app


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(with_fake_repository(create_app(settings)))


def test_the_preview_shows_what_a_node_contributes(client: TestClient) -> None:
    body = client.get(f"/api/v2/nodes/{MATERIAL}", params={"repository": STAGING}).json()
    assert body["node_id"] == MATERIAL and body["kind"] == "material"
    assert body["title"] == "Stationsarbeit zur Optik" and body["description"].startswith("An sechs Stationen")
    assert body["keywords"] == [
        "Auge",
        "Netzhaut",
        "Pupille",
        "Linse",
        "Lochkamera",
        "Stationenlernen",
        "Stationenarbeit",
        "Selbstlernstationen",
    ]
    assert body["subjects"] == ["Biologie", "Physik"] and body["educational_contexts"] == ["Sekundarstufe I"]
    assert body["url"] == "https://www.tutory.de/entdecken/dokument/stationsarbeit-zur-optik-1"
    assert body["repository"] == STAGING
    assert body["render_url"] == f"https://repository.staging.openeduhub.net/edu-sharing/components/render/{MATERIAL}"
    assert body["topic"] == "Optik", "the article the rules find in title and description (D47)"
    assert body["node_article"]["way"] == "rules" and body["node_article"]["entities"][:2] == ["Optik", "Linse"]
    disciplines = "http://w3id.org/openeduhub/vocabs/discipline/"
    assert body["topic_subjects"] == [disciplines + "080", disciplines + "460"], "both, of equal weight"


def test_without_a_repository_the_configured_one_is_asked(client: TestClient) -> None:
    response = client.get(f"/api/v2/nodes/{OPTIK}")
    assert response.status_code == 200
    assert response.json()["repository"] == STAGING and response.json()["kind"] == "collection"


def test_an_empty_repository_counts_as_none(client: TestClient) -> None:
    """The validators read "" as no repository, and so does the service."""
    assert client.get(f"/api/v2/nodes/{OPTIK}", params={"repository": ""}).json()["repository"] == STAGING
    body = {"node_id": OPTIK, "repository": "", "parts": ["world"]}
    assert client.post("/api/v2/compendium", json=body).status_code == 200


def test_a_repository_outside_the_allowlist_is_refused(client: TestClient) -> None:
    response = client.get(f"/api/v2/nodes/{MATERIAL}", params={"repository": "https://example.org/edu-sharing/rest"})
    assert response.status_code == 422
    assert "redaktion.openeduhub.net" in response.text, "the refusal names what is allowed"


@pytest.mark.parametrize("repository", ["https://[::1", "https://repository.staging.openeduhub.net]/"])
def test_a_malformed_repository_address_is_a_422_not_a_server_error(client: TestClient, repository: str) -> None:
    assert client.get(f"/api/v2/nodes/{MATERIAL}", params={"repository": repository}).status_code == 422
    body = {"node_id": MATERIAL, "repository": repository, "parts": ["world"]}
    assert client.post("/api/v2/compendium", json=body).status_code == 422


def test_an_unknown_node_is_a_404_and_a_malformed_id_a_422(client: TestClient) -> None:
    assert client.get(f"/api/v2/nodes/{UNKNOWN}").status_code == 404
    assert client.get("/api/v2/nodes/kein-knoten").status_code == 422


def test_a_compendium_takes_topic_subject_and_levels_from_a_node(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", json={"node_id": OPTIK, "repository": STAGING, "parts": ["world"]})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["topic"] == "Optik" and body["resolution"]["title"] == "Optik"
    assert "Sekundarstufe I" in body["resolution"]["context"], "the node's levels reach the resolution"
    assert body["node"]["title"] == "Optik" and body["node"]["kind"] == "collection"
    assert body["node"]["repository"] == STAGING


def test_a_topic_sent_along_wins_over_the_title_of_the_node(client: TestClient) -> None:
    body = client.post("/api/v2/compendium", json={"node_id": MATERIAL, "topic": "Optik", "parts": ["world"]}).json()
    assert body["topic"] == "Optik"
    assert body["node"]["title"] == "Stationsarbeit zur Optik", "the node still contributes subject and levels"


def test_a_material_without_a_topic_builds_on_the_article_the_rules_find(client: TestClient) -> None:
    """Its title names a format; the rules find the article in title and description (D47, M23)."""
    response = client.post("/api/v2/compendium", json={"node_id": MATERIAL, "repository": STAGING, "parts": ["world"]})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["topic"] == "Optik" and body["resolution"]["query"] == "Stationsarbeit zur Optik"
    node_article = body["audit"]["node_article"]
    assert node_article["way"] == "rules" and node_article["entities"][:2] == ["Optik", "Linse"]
    assert node_article["material"] is None and not node_article["added"]


def test_a_topic_and_a_material_bring_both_articles(client: TestClient) -> None:
    """The topic leads; the material's own article joins as a source of its own when the two link (D47)."""
    response = client.post("/api/v2/knowledge", json={"node_id": MATERIAL, "topic": "Geometrische Optik"})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    origins = {article["title"]: article["origin"] for article in body["articles"]}
    assert origins["Geometrische Optik"] == "primary" and origins["Optik"] == "node"
    assert body["node_article"]["material"] == "Optik" and body["node_article"]["added"]
    compendium = client.post(
        "/api/v2/compendium", json={"node_id": MATERIAL, "topic": "Geometrische Optik", "parts": ["world"]}
    ).json()
    assert "Optik" in [source["title"] for source in compendium["sources"]]


def test_a_material_the_rules_find_no_article_for_asks_for_a_topic(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", json={"node_id": EXAM, "parts": ["world"]})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "topic" in detail["message"] and detail["node_article"]["entities"] == []
    assert client.post("/api/v2/knowledge", json={"node_id": EXAM}).json()["detail"]["message"] == detail["message"]
    with_topic = client.post("/api/v2/compendium", json={"node_id": EXAM, "topic": "Optik", "parts": ["world"]})
    assert with_topic.status_code == 200 and with_topic.json()["topic"] == "Optik", "a topic sent along helps"


def test_a_compendium_needs_a_topic_a_collection_or_a_node(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", json={"parts": ["world"]})
    assert response.status_code == 422 and "node_id" in response.text


def test_knowledge_takes_its_topic_from_a_node(client: TestClient) -> None:
    response = client.post("/api/v2/knowledge", json={"node_id": OPTIK, "repository": STAGING})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["topic"] == "Optik" and body["articles"] and body["node"]["kind"] == "collection"


def test_entities_read_title_description_and_keywords_of_a_node(client: TestClient) -> None:
    response = client.post("/api/v2/entities", json={"node_id": MATERIAL, "repository": STAGING})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert {"Optik", "Linse"} <= {entity["text"] for entity in body["entities"]}
    assert body["node"]["title"] == "Stationsarbeit zur Optik"


def test_entities_need_a_text_or_a_node(client: TestClient) -> None:
    assert client.post("/api/v2/entities", json={}).status_code == 422


def test_qa_takes_its_topic_from_a_node(client: TestClient) -> None:
    response = client.post("/api/v2/qa", json={"node_id": OPTIK, "repository": STAGING})
    assert response.status_code == 200, response.text[:300]
    assert response.json()["topic"] == "Optik"


def test_another_allowed_repository_is_read_anonymously(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    settings = make_settings(
        sample_zims.values(), tmp_path / "state", edu_sharing_user="redaktion", edu_sharing_password="geheim"
    )
    app = with_fake_repository(create_app(settings))
    other = FakeRepository()
    app.state.service.repository_transport = httpx.MockTransport(other)
    response = TestClient(app).get(
        f"/api/v2/nodes/{MATERIAL}", params={"repository": "https://redaktion.openeduhub.net"}
    )
    assert response.status_code == 200 and response.json()["repository"] == PRODUCTION
    assert other.requests and other.requests[0].url.host == "redaktion.openeduhub.net"
    assert "authorization" not in other.requests[0].headers, "the credentials of the configured repository stay there"


def test_the_configured_repository_is_read_anonymously_for_a_node(settings: Settings) -> None:
    app = create_app(settings)
    repo = FakeRepository()
    client = EduSharingClient(BASE, user="redaktion", password="geheim", transport=httpx.MockTransport(repo))
    builder = CollectionBuilder(client=client, cache=None)
    app.state.collections = app.state.service.collections = builder
    assert TestClient(app).get(f"/api/v2/nodes/{MATERIAL}").status_code == 200
    assert repo.requests and "authorization" not in repo.requests[0].headers


def test_a_node_that_is_not_public_is_a_404(client: TestClient) -> None:
    response = client.get(f"/api/v2/nodes/{PRIVATE}")
    assert response.status_code == 404 and "nicht öffentlich" in response.text


def test_the_preview_shows_the_topic_a_request_resolves(settings: Settings) -> None:
    """A title with a subject prefix: the preview gives the topic, subject and context the request uses."""
    answer = _fixture("node_material.json")
    answer["node"]["title"] = "Physik: Optik"
    answer["node"]["properties"]["cclom:title"] = ["Physik: Optik"]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=answer))
    app = create_app(settings)
    builder = CollectionBuilder(client=EduSharingClient(BASE, transport=transport), cache=None)
    app.state.collections = app.state.service.collections = builder
    body = TestClient(app).get(f"/api/v2/nodes/{MATERIAL}").json()
    assert body["title"] == "Physik: Optik"
    assert body["topic"] == "Optik" and body["topic_subjects"] == ["Physik"]
    assert body["context"][:2] == ["Fach Physik", "Sekundarstufe I"]


def test_a_node_carries_the_topic_when_the_collection_cannot_be_read(settings: Settings) -> None:
    """As with a topic sent along: an unreadable collection costs part 3, not the whole compendium."""
    app = with_fake_repository(create_app(settings), FakeRepository(fail=True))
    app.state.service.repository_transport = httpx.MockTransport(FakeRepository())
    body = {"node_id": OPTIK, "repository": PRODUCTION, "collection_id": OPTIK, "parts": ["world"]}
    response = TestClient(app).post("/api/v2/compendium", json=body)
    assert response.status_code == 200, response.text[:300]
    assert response.json()["topic"] == "Optik"


def test_entities_take_a_text_or_a_node_not_both(client: TestClient) -> None:
    """With both, the node would be read for nothing, and its failure would fail a request that has its text."""
    response = client.post("/api/v2/entities", json={"text": "Optik und Linsen", "node_id": MATERIAL})
    assert response.status_code == 422 and "nicht beides" in response.text


def test_the_clients_of_other_repositories_are_closed_at_shutdown(settings: Settings) -> None:
    app = with_fake_repository(create_app(settings))
    app.state.service.repository_transport = httpx.MockTransport(FakeRepository())
    with TestClient(app) as client:
        assert client.get(f"/api/v2/nodes/{MATERIAL}", params={"repository": PRODUCTION}).status_code == 200
        foreign = list(app.state.service._foreign.values())
    assert foreign and all(builder.client._client.is_closed for builder in foreign)


# The shortest body per endpoint a node completes; knowledge, qa and entities need nothing else
NODE_ENDPOINTS = {"/api/v2/compendium": {"parts": ["world"]}, "/api/v2/knowledge": {}, "/api/v2/qa": {}}
NODE_ENDPOINTS["/api/v2/entities"] = {}


@pytest.mark.parametrize("path", list(NODE_ENDPOINTS))
def test_every_endpoint_names_the_failures_of_a_node_alike(
    settings: Settings, sample_zims: dict[str, Path], tmp_path: Path, path: str
) -> None:
    """Refused address 422, unknown node 404, failing repository 502, none configured and none named 503."""
    body = NODE_ENDPOINTS[path]
    working = TestClient(with_fake_repository(create_app(settings)))
    refused = working.post(path, json={**body, "node_id": MATERIAL, "repository": "https://example.org"})
    assert refused.status_code == 422
    assert working.post(path, json={**body, "repository": STAGING}).status_code == 422, "repository needs node_id"
    assert working.post(path, json={**body, "node_id": UNKNOWN}).status_code == 404
    failing = TestClient(with_fake_repository(create_app(settings), FakeRepository(fail=True)))
    assert failing.post(path, json={**body, "node_id": MATERIAL}).status_code == 502
    unconfigured = make_settings(sample_zims.values(), tmp_path / "state", edu_sharing_base_url="")
    assert TestClient(create_app(unconfigured)).post(path, json={**body, "node_id": MATERIAL}).status_code == 503


def test_part_two_searches_every_subject_of_a_node(client: TestClient) -> None:
    body = {"node_id": MATERIAL, "topic": "Optik", "parts": ["world", "curricula"]}
    response = client.post("/api/v2/compendium", json=body)
    assert response.status_code == 200, response.text[:300]
    assert {"biologie", "physik"} <= set(response.json()["curricula"]["subject_terms"])


def test_with_article_choice_llm_the_model_names_the_article_of_a_material(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One question with title, subjects, keywords and description (M21 S4); its tokens count in the audit."""
    app = with_fake_repository(create_app(settings))

    def answer(body: dict[str, Any]) -> str:
        asks_for_topic = "Unterrichtsmaterial das fachliche Thema" in body["messages"][0]["content"]
        return json.dumps({"titel": "Geometrische Optik"} if asks_for_topic else {})

    fake = FakeBApi(answer)
    monkeypatch.setattr(app.state.service, "llm", make_gateway(fake, per_request=100_000))
    payload = {"node_id": MATERIAL, "parts": ["world"], "article_choice": "llm"}
    body = TestClient(app).post("/api/v2/compendium", json=payload).json()
    assert body["topic"] == "Geometrische Optik"
    assert body["audit"]["node_article"]["way"] == "llm" and body["audit"]["node_article"]["named"] == body["topic"]
    assert body["audit"]["llm"]["article_choice"]["used"] == "llm"
    assert "node_topic@v1" in body["frontmatter"]["llm"]["prompts"]
    assert body["audit"]["llm_tokens"]["calls"] == len(fake.bodies) == 2, "the question and the check of side articles"


def _with_llm(settings: Settings, monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any]) -> tuple[TestClient, Any]:
    app = with_fake_repository(create_app(settings))
    fake = FakeBApi(lambda body: json.dumps(answer))
    monkeypatch.setattr(app.state.service, "llm", make_gateway(fake, per_request=100_000))
    return TestClient(app), fake


def test_the_404_says_what_was_tried_for_a_material(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Asked and found nothing is another message than never asked; a topic that is not found keeps its own."""
    client, _ = _with_llm(settings, monkeypatch, {"titel": "Qwertzuiopü"})
    asked = client.post("/api/v2/compendium", json={"node_id": EXAM, "article_choice": "llm", "parts": ["world"]})
    assert asked.status_code == 404 and "LLM" in asked.json()["detail"]["message"]
    assert "article_choice" not in asked.json()["detail"]["message"], "it was asked already"
    client, _ = _with_llm(settings, monkeypatch, {"titel": ""})
    nothing = client.post("/api/v2/compendium", json={"node_id": EXAM, "article_choice": "llm", "parts": ["world"]})
    assert nothing.status_code == 404 and "kein fachliches Thema" in nothing.json()["detail"]["message"]
    topic = client.post("/api/v2/compendium", json={"node_id": EXAM, "topic": "Qwertzuiopü", "parts": ["world"]})
    detail = topic.json()["detail"]
    assert topic.status_code == 404 and detail["message"] == "Thema in den Archiven nicht gefunden"
    assert detail["node_article"]["way"] == "rules", "the material's search is shown with a topic too"


def test_part_three_alone_asks_the_llm_nothing_about_a_material(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fake = _with_llm(settings, monkeypatch, {"titel": "Optik"})
    body = {"node_id": MATERIAL, "collection_id": OPTIK, "parts": ["collection"], "article_choice": "llm"}
    response = client.post("/api/v2/compendium", json=body)
    assert response.status_code == 200, response.text[:300]
    assert fake.bodies == [], "part 3 needs no article; the rules name the topic"


def test_an_unknown_knowledge_collection_is_a_404_as_an_unknown_collection_is(client: TestClient) -> None:
    body = {"topic": "Optik", "knowledge_collection_id": UNKNOWN, "parts": ["world"]}
    answer = client.post("/api/v2/compendium", json=body)
    assert answer.status_code == 404 and UNKNOWN in answer.text


def test_a_collection_without_a_configured_repository_is_named_not_hidden(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    """A collection as the only source of the topic was a 404 for the empty topic ""; the knowledge collection
    vanished without a word (review of 2026-09-25)."""
    client = TestClient(create_app(make_settings(sample_zims.values(), tmp_path / "state", edu_sharing_base_url="")))
    alone = client.post("/api/v2/compendium", json={"collection_id": OPTIK, "parts": ["world"]})
    assert alone.status_code == 503 and "EDU_SHARING_BASE_URL" in alone.text
    body = {"topic": "Optik", "knowledge_collection_id": OPTIK, "parts": ["world"]}
    knowledge = client.post("/api/v2/compendium", json=body).json()["audit"]["knowledge"]
    assert knowledge["sources"] == 0 and "EDU_SHARING_BASE_URL" in knowledge["error"]
