"""A node of an edu-sharing repository as input of the endpoints (D45), and a preview of what is read from it.

``node_id`` and ``repository`` go into compendium, knowledge, qa and entities; ``GET /api/v2/nodes/{id}`` shows the
metadata and the topic the service would derive. The configured repository is read with its credentials, every
other allowed one anonymously - the credentials of one repository never travel to another.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.conftest import make_settings
from tests.test_wlo_client import BASE, MATERIAL, OPTIK, UNKNOWN, FakeRepository

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
    assert body["keywords"] == ["Auge", "Netzhaut", "Pupille", "Linse", "Lochkamera"]
    assert body["subjects"] == ["Physik"] and body["educational_contexts"] == ["Sekundarstufe I"]
    assert body["url"] == "https://example.org/stationsarbeit-optik"
    assert body["repository"] == STAGING
    assert body["render_url"] == f"https://repository.staging.openeduhub.net/edu-sharing/components/render/{MATERIAL}"
    assert body["topic"] == "Stationsarbeit zur Optik", "the topic the service would resolve"


def test_without_a_repository_the_configured_one_is_asked(client: TestClient) -> None:
    response = client.get(f"/api/v2/nodes/{OPTIK}")
    assert response.status_code == 200
    assert response.json()["repository"] == STAGING and response.json()["kind"] == "collection"


def test_a_repository_outside_the_allowlist_is_refused(client: TestClient) -> None:
    response = client.get(f"/api/v2/nodes/{MATERIAL}", params={"repository": "https://example.org/edu-sharing/rest"})
    assert response.status_code == 422
    assert "redaktion.openeduhub.net" in response.text, "the refusal names what is allowed"


def test_an_unknown_node_is_a_404_and_a_malformed_id_a_422(client: TestClient) -> None:
    assert client.get(f"/api/v2/nodes/{UNKNOWN}").status_code == 404
    assert client.get("/api/v2/nodes/kein-knoten").status_code == 422


def test_a_compendium_takes_topic_subject_and_levels_from_a_node(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", json={"node_id": OPTIK, "repository": STAGING, "parts": ["world"]})
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["topic"] == "Optik" and body["resolution"]["title"] == "Optik"
    assert body["node"]["title"] == "Optik" and body["node"]["kind"] == "collection"
    assert body["node"]["repository"] == STAGING


def test_a_topic_sent_along_wins_over_the_title_of_the_node(client: TestClient) -> None:
    body = client.post("/api/v2/compendium", json={"node_id": MATERIAL, "topic": "Optik", "parts": ["world"]}).json()
    assert body["topic"] == "Optik"
    assert body["node"]["title"] == "Stationsarbeit zur Optik", "the node still contributes subject and levels"


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
