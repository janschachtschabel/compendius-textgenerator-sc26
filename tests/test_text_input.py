"""A node, a collection and a knowledge collection given as text give what the repository's facts give (D114).

Jan, 2026-11-04: every function should run on text input alone; the place of a collection in its topic tree, which
lifts the article choice for neutral titles (M71), must come along as text as well. The test is equality, not a new
measurement: the same facts as text give the same text without an LLM and the same prompt with one.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domain.requests import GenerateRequest
from app.domain.text_input import CollectionText, MaterialText
from app.main import create_app
from app.service import CompendiumService
from app.settings import Settings
from app.sources.lehrplan.subjects import UnknownSubjectError
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.test_collection_context import BASE, NODE, PARENT, PHYSIK, FakeTree, _builder
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

GRUNDLAGEN = CollectionText(
    title="Grundlagen",
    path=["Optik"],
    children=["Lichtausbreitung", "Schatten"],
    materials=["Was ist Licht?", "Schattenbildung im Versuch"],
    neighbours=["Linsen", "Optische Geräte"],
    subjects=["Physik"],
)
MATERIAL_ID = "44444444-dddd-4ddd-8ddd-000000000001"
STATIONS = MaterialText(
    title="Stationsarbeit zur Optik",
    description="An Stationen untersuchen die Lernenden, wie Licht an Linsen gebrochen wird und Bilder entstehen.",
    keywords=["Licht", "Linse"],
    subjects=["Physik"],
    levels=["Sekundarstufe I"],
)


def _material_node() -> dict[str, Any]:
    props = {
        "cm:title": [STATIONS.title],
        "cclom:general_description": [STATIONS.description],
        "cclom:general_keyword": list(STATIONS.keywords),
        "ccm:taxonid": [PHYSIK],
        "ccm:taxonid_DISPLAYNAME": ["Physik"],
        "ccm:educationalcontext": ["http://w3id.org/openeduhub/vocabs/educationalContext/sekundarstufe_1"],
        "ccm:educationalcontext_DISPLAYNAME": ["Sekundarstufe I"],
    }
    return {"ref": {"id": MATERIAL_ID}, "title": STATIONS.title, "aspects": [], "properties": props}


def _material_repository(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith(f"/nodes/-home-/{MATERIAL_ID}/metadata"):
        return httpx.Response(200, json={"node": _material_node()})
    return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def in_tree(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> FakeTree:
    fake = FakeTree()
    monkeypatch.setattr(service, "collections", _builder(fake))
    return fake


@pytest.fixture
def with_material(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    client = EduSharingClient(BASE, transport=httpx.MockTransport(_material_repository))
    monkeypatch.setattr(service, "collections", CollectionBuilder(client=client, cache=None))


def _texts(service: CompendiumService, request: GenerateRequest) -> tuple[str, str, list[str]]:
    result = service.generate(request)
    return result.topic, result.resolution.title, [section.text for section in result.sections]


# -- the same compendium ----------------------------------------------------------------------------------------------


def test_a_collection_as_text_gives_the_compendium_of_the_collection_node(
    service: CompendiumService, in_tree: FakeTree
) -> None:
    by_node = _texts(service, GenerateRequest(node_id=NODE, parts=["world"], preset="llm-free"))
    reads = len(in_tree.requests)

    by_text = _texts(service, GenerateRequest(collection_context=GRUNDLAGEN, parts=["world"], preset="llm-free"))

    assert by_text == by_node
    assert by_node[:2] == ("Grundlagen (Optik)", "Optik")
    assert len(in_tree.requests) == reads, "the text input reads nothing of the repository"


def test_the_question_n_hears_the_same_place_from_the_text(
    service: CompendiumService, in_tree: FakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    def asked(request: GenerateRequest) -> str:
        fake = FakeBApi(lambda body: json.dumps({"uebersicht": "Optik", "artikel": ["Geometrische Optik"]}))
        monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))
        service.generate(request)
        prompts = [b["messages"][1]["content"] for b in fake.bodies if "Übersichtsartikel" in b["messages"][1]["content"]]
        return prompts[0]

    by_node = asked(GenerateRequest(node_id=NODE, parts=["world"], preset="balanced"))
    by_text = asked(GenerateRequest(collection_context=GRUNDLAGEN, parts=["world"], preset="balanced"))

    assert by_text == by_node
    assert "nicht gemeint sind die Nachbarsammlungen: Linsen, Optische Geräte" in by_text


def test_a_material_as_text_gives_the_compendium_of_the_material_node(
    service: CompendiumService, with_material: None
) -> None:
    by_node = _texts(service, GenerateRequest(node_id=MATERIAL_ID, parts=["world"], preset="llm-free"))
    by_text = _texts(service, GenerateRequest(material=STATIONS, parts=["world"], preset="llm-free"))

    assert by_text == by_node
    assert by_node[1] == "Optik"


def test_the_node_preview_returns_the_text_input_that_gives_the_same_compendium(
    settings: Settings, service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeTree()
    with TestClient(create_app(settings)) as client:
        monkeypatch.setattr(client.app.state.service, "collections", _builder(fake))  # type: ignore[attr-defined]
        preview = client.get(f"/api/v2/nodes/{NODE}").json()

    assert preview["text_input"] == {"collection_context": {**GRUNDLAGEN.model_dump(), "levels": []}}
    assert preview["topic"] == "Optik"


def test_the_preview_of_a_material_names_its_fields_as_text(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app(settings)) as client:
        client_builder = CollectionBuilder(
            client=EduSharingClient(BASE, transport=httpx.MockTransport(_material_repository)), cache=None
        )
        monkeypatch.setattr(client.app.state.service, "collections", client_builder)  # type: ignore[attr-defined]
        preview = client.get(f"/api/v2/nodes/{MATERIAL_ID}").json()

    assert preview["text_input"] == {"material": STATIONS.model_dump()}


# -- texts as sources -------------------------------------------------------------------------------------------------


def test_texts_feed_part_1_as_cited_materials(service: CompendiumService) -> None:
    text = "\n".join(
        [
            "Im Unterricht bauen die Lernenden eine Lochkamera und beobachten, wie das Bild auf dem Kopf steht.",
            "Kurz.",  # under 40 characters: no paragraph
        ]
    )
    result = service.generate(
        GenerateRequest(
            topic="Optik",
            sources=[{"title": "Lochkamera im Unterricht", "text": text, "license": "CC BY 4.0", "authors": ["A. B."]}],
            parts=["world"],
            preset="llm-free",
        )
    )

    assert result.audit.text_sources == {"sent": 1, "sources": 1, "empty": 0}
    source = next(s for s in result.sources if s.source_id == "text:1")
    assert (source.title, source.project, source.license) == ("Lochkamera im Unterricht", "text_material", "CC BY 4.0")


def test_a_text_without_a_line_worth_citing_is_counted_empty(service: CompendiumService) -> None:
    result = service.generate(
        GenerateRequest(topic="Optik", sources=[{"title": "Notiz", "text": "zu kurz"}], parts=["world"], preset="llm-free")
    )
    assert result.audit.text_sources == {"sent": 1, "sources": 0, "empty": 1}


# -- what the request refuses -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"node_id": NODE, "collection_context": {"title": "Grundlagen"}},
        {"node_id": NODE, "material": {"title": "Arbeitsblatt"}},
        {"material": {"title": "Arbeitsblatt"}, "collection_context": {"title": "Grundlagen"}},
    ],
)
def test_one_node_per_request_read_or_as_text(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="schließen sich aus"):
        GenerateRequest(**fields)


def test_sources_need_part_1() -> None:
    with pytest.raises(ValidationError, match="sources speisen Teil 1"):
        GenerateRequest(topic="Optik", sources=[{"title": "T", "text": "x" * 50}], parts=["curricula"])


def test_a_text_input_alone_names_the_topic() -> None:
    assert GenerateRequest(material={"title": "Arbeitsblatt"}).names_topic
    assert GenerateRequest(collection_context={"title": "Grundlagen"}).names_topic


def test_an_unknown_subject_of_a_text_input_is_refused_before_any_reading(service: CompendiumService) -> None:
    with pytest.raises(UnknownSubjectError):
        service.prepare(GenerateRequest(material={"title": "Arbeitsblatt", "subjects": ["Fyzik"]}, parts=["world"]))


def test_qa_and_knowledge_take_the_text_input(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTree()
    with TestClient(create_app(settings)) as client:
        monkeypatch.setattr(client.app.state.service, "collections", _builder(fake))  # type: ignore[attr-defined]
        context = GRUNDLAGEN.model_dump()
        knowledge = client.post("/api/v2/knowledge", json={"collection_context": context, "preset": "llm-free"})
        qa = client.post("/api/v2/qa", json={"collection_context": context, "preset": "llm-free", "count": 2})

    assert knowledge.status_code == 200, knowledge.text
    assert knowledge.json()["resolution"]["title"] == "Optik"
    assert qa.status_code == 200, qa.text
    assert not fake.requests, "nothing of the repository is read"
    assert PARENT not in json.dumps(knowledge.json())
