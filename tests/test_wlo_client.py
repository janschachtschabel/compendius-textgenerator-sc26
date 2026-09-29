"""edu-sharing client: URL building, pagination, auth, error mapping, id validation (offline, mocked transport)."""

import base64
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from app.sources.wlo.client import CollectionNotFoundError, EduSharingClient, EduSharingError, validate_node_id
from app.sources.wlo.errors import TimeUpError

FIX = Path(__file__).parent / "fixtures" / "wlo"
BASE = "https://repo.test/edu-sharing/rest"
OPTIK = "9e7ae956-e9df-430f-bace-f3db4b910013"
UNKNOWN = "00000000-0000-4000-8000-000000000000"
MATERIAL = "ac66224b-42b0-4676-a53d-71b058dc780b"  # a material of the staging repository
PRIVATE = "22222222-2222-4222-8222-222222222222"
EXAM = "33333333-3333-4333-8333-333333333333"  # a material whose title and description name no article (D47)
NODE_FIXTURES = {
    OPTIK: "node_collection_optik.json",
    MATERIAL: "node_material.json",
    EXAM: "node_material_ohne_artikel.json",
}


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
        if PRIVATE in path:  # a node the reader may not see
            return httpx.Response(403, json={"error": "org.edu_sharing.restservices.DAOSecurityException"})
        if path.endswith("/metadata") and "/node/v1/nodes/-home-/" in path:
            name = NODE_FIXTURES.get(path.split("/")[-2])
            if name is None:
                return httpx.Response(404, json={"error": "org.edu_sharing.restservices.DAOMissingException"})
            return httpx.Response(200, json=_fixture(name))
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


def test_error_messages_carry_no_repository_internals(caplog: pytest.LogCaptureFixture) -> None:
    client = _client(FakeRepository())
    with caplog.at_level("WARNING"), pytest.raises(EduSharingError) as failure:
        client.text_content("11111111-1111-4111-8111-111111111111")
    assert str(failure.value) == "edu-sharing antwortete mit HTTP 500"  # shown to API clients and in part 3
    assert BASE in caplog.text  # the details stay in the log


def test_pagination_stops_at_the_page_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    def endless(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["skipCount"])
        nodes = [{"ref": {"id": f"00000000-0000-4000-8000-{skip + i:012d}"}, "properties": {}} for i in range(2)]
        return httpx.Response(200, json={"references": nodes})  # always a full page, never a total

    monkeypatch.setattr("app.sources.wlo.client.MAX_PAGES", 3)
    client = EduSharingClient(BASE, transport=httpx.MockTransport(endless), page_size=2)
    assert len(client.references(OPTIK)) == 6


def test_a_repository_that_ignores_the_offset_is_not_paged_to_the_cap() -> None:
    requests: list[httpx.Request] = []

    def same_page(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        nodes = [{"ref": {"id": f"00000000-0000-4000-8000-{i:012d}"}, "properties": {}} for i in range(2)]
        return httpx.Response(200, json={"references": nodes, "pagination": {"total": 5000}})  # skipCount ignored

    client = EduSharingClient(BASE, transport=httpx.MockTransport(same_page), page_size=2)
    assert len(client.references(OPTIK)) == 2
    assert len(requests) == 2  # the second page brought nothing new; MAX_PAGES pages took about 80 s before


def test_overlapping_pages_keep_the_listing_going() -> None:
    def overlapping(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["skipCount"])
        start = max(0, skip - 1)  # every page repeats the last reference of the one before
        nodes = [
            {"ref": {"id": f"00000000-0000-4000-8000-{i:012d}"}, "properties": {}} for i in range(start, start + 2)
        ]
        return httpx.Response(200, json={"references": nodes, "pagination": {"total": 7}})

    client = EduSharingClient(BASE, transport=httpx.MockTransport(overlapping), page_size=2)
    assert len(client.references(OPTIK)) == 7  # a repeated id is no reason to stop


def test_the_warning_names_the_page_that_repeats(caplog: pytest.LogCaptureFixture) -> None:
    def same_page(request: httpx.Request) -> httpx.Response:
        nodes = [{"ref": {"id": f"00000000-0000-4000-8000-{i:012d}"}, "properties": {}} for i in range(2)]
        return httpx.Response(200, json={"references": nodes, "pagination": {"total": 5000}})

    client = EduSharingClient(BASE, transport=httpx.MockTransport(same_page), page_size=2)
    with caplog.at_level("WARNING"):
        client.references(OPTIK)
    assert "offset 2 " in caplog.text  # the page requested with skipCount=2, to be reproduced with curl


def test_the_public_url_of_a_node_is_built_from_the_repository_host() -> None:
    """The render URL opens the node's page and validates the id, so a crafted id cannot be written into a
    link the compendium publishes."""
    client = _client(FakeRepository())
    assert client.render_url(OPTIK) == f"https://repo.test/edu-sharing/components/render/{OPTIK}"
    with pytest.raises(ValueError):
        client.render_url("../secret")


def test_the_anonymous_node_read_carries_no_session_of_the_account() -> None:
    """edu-sharing may answer a login with a session cookie. Kept by the client, it rode along on the node reads that
    go without credentials, and a node only the account may see became readable through the endpoints without a
    login (audit 2026-09-29, A02) - also when reads with and without the account run side by side."""
    seen: list[httpx.Request] = []

    def repository(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith(f"/collections/-home-/{OPTIK}"):
            session = {"Set-Cookie": "JSESSIONID=4711; Path=/edu-sharing; Secure; HttpOnly"}
            return httpx.Response(200, json=_fixture("collection_optik.json"), headers=session)
        return httpx.Response(200, json=_fixture("node_material.json"))

    client = EduSharingClient(BASE, user="redaktion", password="geheim", transport=httpx.MockTransport(repository))
    client.collection(OPTIK)
    client.node(MATERIAL)
    client.node(MATERIAL)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: client.collection(OPTIK) if i % 2 else client.node(MATERIAL), range(40)))
    nodes = [request for request in seen if request.url.path.endswith("/metadata")]
    assert len(nodes) == 22
    assert not [request.headers for request in nodes if {"authorization", "cookie"} & set(request.headers.keys())]
    assert not [request.headers for request in seen if "cookie" in request.headers], "no client keeps a session"


def test_closing_the_client_closes_the_connections_with_and_without_the_account() -> None:
    client = _client(FakeRepository(), user="redaktion", password="geheim")
    client.close()
    with pytest.raises(RuntimeError, match="closed"):
        client.collection(OPTIK)
    with pytest.raises(RuntimeError, match="closed"):
        client.node(MATERIAL)


def _answering(body: object) -> EduSharingClient:
    """A client whose repository answers every request with ``body`` as JSON, ``None`` as ``null``."""

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(body).encode(), headers={"Content-Type": "application/json"})

    return EduSharingClient(BASE, transport=httpx.MockTransport(answer))


READS: dict[str, Callable[[EduSharingClient], object]] = {
    "collection": lambda client: client.collection(OPTIK),
    "subcollections": lambda client: client.subcollections(OPTIK),
    "references": lambda client: client.references(OPTIK),
    "node": lambda client: client.node(MATERIAL),
    "text": lambda client: client.text_content(MATERIAL),
}
REFERENCE = {"ref": {"id": MATERIAL}, "properties": {}}


@pytest.mark.parametrize("body", [[], None, "Optik", 16, [{"collection": {}}]])
def test_an_answer_that_is_no_object_is_a_repository_error(body: object) -> None:
    """``null`` was taken for a missing node (a 404), a list failed at ``.get`` (a 500) (audit 2026-09-29, A09)."""
    for name, read in READS.items():
        with pytest.raises(EduSharingError, match="nicht mit einem JSON-Objekt") as failure:
            read(_answering(body))
        assert type(failure.value) is EduSharingError, name


@pytest.mark.parametrize(
    ("read", "body"),
    [
        ("collection", {"collection": []}),
        ("collection", {"collection": None}),
        ("collection", {"collection": {"properties": ["cm:title"]}}),
        ("collection", {"collection": {"ref": "x"}}),
        ("collection", {"collection": {"ref": {"id": 16}}}),
        ("references", {"references": {}}),
        ("references", {"nodes": "x"}),
        ("references", {"references": [MATERIAL]}),
        ("references", {"references": [{**REFERENCE, "properties": []}]}),
        ("references", {"references": [{**REFERENCE, "ref": [MATERIAL]}]}),
        ("references", {"references": [{**REFERENCE, "ref": {"id": {"id": MATERIAL}}}]}),
        ("references", {"references": [{**REFERENCE, "content": "x"}]}),
        ("references", {"references": [{**REFERENCE, "originalId": {"id": MATERIAL}}]}),
        ("references", {"references": [REFERENCE], "pagination": []}),
        ("references", {"references": [REFERENCE], "pagination": {"total": "16"}}),
        ("subcollections", {"collections": {}}),
        ("subcollections", {"collections": ["Farben"]}),
        ("subcollections", {"collections": [{"ref": {"id": OPTIK}, "properties": 5}]}),
        ("node", {"node": "x"}),
        ("node", {"node": {"properties": []}}),
        ("node", {"node": {"aspects": 5, "properties": {}}}),
    ],
)
def test_an_answer_of_another_shape_is_a_repository_error(read: str, body: object) -> None:
    """An object where a list belongs, a list where an object does, a number where a text does: the repository's
    failure (502, a hint in part 3), not an AttributeError or a TypeError of the service (500) (audit 2026-09-29, A09).
    """
    with pytest.raises(EduSharingError, match="edu-sharing antwortete"):
        READS[read](_answering(body))


@pytest.mark.parametrize(
    ("read", "body", "expected"),
    [
        ("references", {}, []),
        ("references", {"references": None}, []),
        ("references", {"references": [], "pagination": {"total": 0}}, []),
        ("subcollections", {}, []),
        ("subcollections", {"collections": None}, []),
        ("text", {}, ""),
    ],
)
def test_empty_answers_stay_valid(read: str, body: object, expected: object) -> None:
    assert READS[read](_answering(body)) == expected


def test_a_collection_answer_without_its_id_keeps_the_id_asked_for() -> None:
    """As a node does: the id of the request is checked, the answer's is not - without one, part 3 failed at the
    link of the collection with a ValueError (a 500)."""
    info = _answering({"collection": {"title": "Optik"}}).collection(OPTIK)
    assert info.id == OPTIK and info.title == "Optik"


def test_no_request_starts_once_the_time_budget_is_spent() -> None:
    repo = FakeRepository()
    client = _client(repo)
    for read in (client.collection, client.subcollections, client.references, client.text_content):
        with pytest.raises(TimeUpError, match="Zeitbudget der Anfrage erschöpft"):
            read(OPTIK, remaining=lambda: 0.0)
    assert repo.requests == []


def test_a_listing_ends_after_the_last_page_that_came_in_time() -> None:
    repo = FakeRepository()
    left = iter([60.0, 0.0])
    refs = _client(repo).references(OPTIK, remaining=lambda: next(left))
    assert len(refs) == 10 and len(repo.requests) == 1  # the first of two pages


def test_a_request_waits_at_most_the_time_left_and_the_client_timeout() -> None:
    repo = FakeRepository()
    client = EduSharingClient(BASE, transport=httpx.MockTransport(repo), timeout_s=30.0)
    client.collection(OPTIK, remaining=lambda: 2.5)
    client.collection(OPTIK, remaining=lambda: 90.0)
    client.collection(OPTIK)
    assert [request.extensions["timeout"] for request in repo.requests] == [
        dict.fromkeys(("connect", "read", "write", "pool"), seconds) for seconds in (2.5, 30.0, 30.0)
    ]


def test_a_request_the_budget_ends_is_not_tried_again() -> None:
    """A dropped connection is tried again (ATTEMPTS), but not once the budget is spent."""
    requests: list[httpx.Request] = []

    def slow(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("too slow for the time left", request=request)

    client = EduSharingClient(BASE, transport=httpx.MockTransport(slow))
    left = iter([1.0, 0.0])
    with pytest.raises(TimeUpError):
        client.collection(OPTIK, remaining=lambda: next(left))
    assert len(requests) == 1
    with pytest.raises(EduSharingError, match="nicht erreichbar"):
        client.collection(OPTIK, remaining=lambda: 60.0)
    assert len(requests) == 3


def test_a_sub_collection_without_an_id_is_left_out_as_a_reference_without_one_is() -> None:
    """Its materials are read by its id; an empty one failed there with a ValueError (a 500)."""
    listed = {"ref": {"id": OPTIK}, "properties": {"cm:title": ["Farben"]}}
    subs = _answering({"collections": [{"properties": {"cm:title": ["ohne Kennung"]}}, listed]}).subcollections(OPTIK)
    assert [sub.id for sub in subs] == [OPTIK]


VALID = "44444444-4444-4444-8444-444444444444"


def test_an_entry_whose_id_is_no_node_id_is_left_out() -> None:
    """A listing entry whose id is text but no node id raised a ValueError where it became part of a URL - the
    materials of a sub-collection, the text of a material - and the request a 500 (audit 2026-09-29, A09). It is left
    out like an entry without an id; an originalId of that kind yields to the reference's own."""

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/children/references"):
            nodes = [
                {"ref": {"id": "keine-uuid"}, "properties": {}},
                {"ref": {"id": VALID}, "originalId": "auch-keine", "properties": {}},
            ]
            return httpx.Response(200, json={"references": nodes, "pagination": {"total": 2}})
        if request.url.path.endswith("/children/collections"):
            return httpx.Response(200, json={"collections": [{"ref": {"id": "x"}}, {"ref": {"id": VALID}}]})
        return httpx.Response(404, json={})

    client = EduSharingClient(BASE, transport=httpx.MockTransport(answer))

    refs = client.references(OPTIK)
    subs = client.subcollections(OPTIK)

    assert [ref.id for ref in refs] == [VALID] and refs[0].node_id == VALID
    assert [sub.id for sub in subs] == [VALID]
