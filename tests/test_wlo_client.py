"""edu-sharing client: URL building, pagination, auth, error mapping, id validation (offline, mocked transport)."""

import base64
import json
from pathlib import Path

import httpx
import pytest

from app.sources.wlo.client import CollectionNotFoundError, EduSharingClient, EduSharingError, validate_node_id

FIX = Path(__file__).parent / "fixtures" / "wlo"
BASE = "https://repo.test/edu-sharing/rest"
OPTIK = "9e7ae956-e9df-430f-bace-f3db4b910013"
UNKNOWN = "00000000-0000-4000-8000-000000000000"


def _fixture(name: str) -> dict:  # type: ignore[type-arg]
    data: dict = json.loads((FIX / name).read_text(encoding="utf-8"))  # type: ignore[type-arg]
    return data


class FakeRepository:
    """Answers like redaktion.openeduhub.net did on 2026-09-17 and records every request."""

    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("boom")
        path, params = request.url.path, request.url.params
        if "11111111-1111-4111-8111-111111111111" in path:
            return httpx.Response(500, text="Internal Server Error")
        if f"/collections/-home-/{UNKNOWN}" in path:
            return httpx.Response(404, json={"error": "org.edu_sharing.restservices.DAOMissingException"})
        if path.endswith("/children/references"):
            page = "references_optik_page1.json" if params.get("skipCount") == "0" else "references_optik_page2.json"
            return httpx.Response(200, json=_fixture(page))
        if path.endswith("/children/collections"):
            return httpx.Response(200, json=_fixture("subcollections_optik.json"))
        if path.endswith(f"/collections/-home-/{OPTIK}"):
            return httpx.Response(200, json=_fixture("collection_optik.json"))
        if path.endswith("/textContent"):
            node_id = path.split("/")[-2]
            entry = _fixture("textcontent_optik.json").get(node_id)
            if entry is None:
                return httpx.Response(404, json={"error": "missing"})
            return httpx.Response(entry["status"], json=entry["body"])
        return httpx.Response(500, text="unexpected path " + path)


def _client(repo: FakeRepository, **kwargs: object) -> EduSharingClient:
    return EduSharingClient(BASE, transport=httpx.MockTransport(repo), page_size=10, **kwargs)  # type: ignore[arg-type]


def test_collection_metadata_and_subcollections() -> None:
    repo = FakeRepository()
    client = _client(repo)
    info = client.collection(OPTIK)
    assert info.title == "Optik" and info.subject_labels == ("Physik",)
    assert [sub.title for sub in client.subcollections(OPTIK)][:2] == ["Geometrische Optik", "Farben"]
    assert repo.requests[0].url.path == f"/edu-sharing/rest/collection/v1/collections/-home-/{OPTIK}"
    assert repo.requests[0].headers["accept"] == "application/json"
    assert "authorization" not in repo.requests[0].headers  # anonymous without credentials


def test_references_are_paginated_until_the_total_is_reached() -> None:
    repo = FakeRepository()
    refs = _client(repo).references(OPTIK)
    assert len(refs) == 16 and len({ref.id for ref in refs}) == 16
    pages = [r for r in repo.requests if r.url.path.endswith("/children/references")]
    assert [(p.url.params["skipCount"], p.url.params["maxItems"]) for p in pages] == [("0", "10"), ("10", "10")]
    assert all(p.url.params["propertyFilter"] == "-all-" for p in pages)


def test_text_content_returns_plain_text_or_empty_for_missing_nodes() -> None:
    client = _client(FakeRepository())
    text = client.text_content("454327ba-848e-4245-b89a-2d8d68eb3dc0")
    assert text.startswith("Licht") and len(text) > 1000
    assert client.text_content(UNKNOWN) == ""


def test_credentials_are_sent_as_basic_auth() -> None:
    repo = FakeRepository()
    _client(repo, user="svc", password="s3cret").collection(OPTIK)
    expected = "Basic " + base64.b64encode(b"svc:s3cret").decode()
    assert repo.requests[0].headers["authorization"] == expected


def test_errors_are_mapped_and_ids_validated() -> None:
    client = _client(FakeRepository())
    with pytest.raises(CollectionNotFoundError):
        client.collection(UNKNOWN)
    with pytest.raises(EduSharingError, match="HTTP 500"):
        client.text_content("11111111-1111-4111-8111-111111111111")
    with pytest.raises(EduSharingError, match="nicht erreichbar"):
        _client(FakeRepository(fail=True)).collection(OPTIK)
    for bad in ("../x", "9e7ae956", "", "9e7ae956-e9df-430b-bace-f3db4b910013/children"):
        with pytest.raises(ValueError):
            validate_node_id(bad)
    assert validate_node_id(OPTIK) == OPTIK
