"""A node of an edu-sharing repository as input (D45): its metadata, the repository address, the derived topic.

A material or a collection comes with title, description, keywords, subject and educational level; the service
reads them from ``/node/v1/nodes/-home-/{id}/metadata``. The fixtures are that answer of the staging repository of
2026-09-24 for a material and a collection, cut to the fields the service reads; the material's description is a
synthetic text. The repository a request names is caller input, so only https addresses of allowed hosts pass, and
the path is always the REST root - nothing else of the address counts.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient, EduSharingError, NodeNotFoundError
from app.sources.wlo.models import NodeInfo, parse_node
from app.sources.wlo.part import CollectionBuilder, CollectionTopic, derive_topic, node_input, node_topic
from app.sources.wlo.repository import RepositoryNotAllowedError, repository_root
from tests.test_wlo_client import BASE, MATERIAL, OPTIK, PRIVATE, UNKNOWN, FakeRepository, _client, _fixture

STAGING = "https://repository.staging.openeduhub.net/edu-sharing/rest"
ALLOWED = frozenset({"repository.staging.openeduhub.net", "redaktion.openeduhub.net"})
PHYSIK = "http://w3id.org/openeduhub/vocabs/discipline/460"
BIOLOGIE = "http://w3id.org/openeduhub/vocabs/discipline/080"
TUTORY = "https://www.tutory.de/entdecken/dokument/stationsarbeit-zur-optik-1"


def test_a_material_node_gives_title_description_keywords_subject_and_level() -> None:
    info = _client(FakeRepository()).node(MATERIAL)
    assert info.node_id == MATERIAL and info.kind == "material"
    assert info.title == "Stationsarbeit zur Optik"
    assert info.description.startswith("An sechs Stationen untersuchen Lernende")
    assert info.keywords == (
        "Auge",
        "Netzhaut",
        "Pupille",
        "Linse",
        "Lochkamera",
        "Stationenlernen",
        "Stationenarbeit",
        "Selbstlernstationen",
    )
    assert info.subject_uris == (BIOLOGIE, PHYSIK) and info.subject_labels == ("Biologie", "Physik")
    assert info.educational_contexts == ("Sekundarstufe I",)
    assert info.url == TUTORY


def test_a_collection_node_reads_the_same_way_and_says_what_it_is() -> None:
    info = _client(FakeRepository()).node(OPTIK)
    assert info.kind == "collection" and info.title == "Optik"
    assert "Linse" in info.keywords and info.subject_labels == ("Physik",)
    assert info.description == "", "the collection of the staging repository has no description"


def test_the_metadata_endpoint_is_asked_for_all_properties() -> None:
    repo = FakeRepository()
    _client(repo).node(MATERIAL)
    request = repo.requests[-1]
    assert request.url.path.endswith(f"/node/v1/nodes/-home-/{MATERIAL}/metadata")
    assert request.url.params["propertyFilter"] == "-all-"


def test_an_unknown_node_is_not_found_and_a_malformed_id_never_reaches_the_url() -> None:
    repo = FakeRepository()
    with pytest.raises(NodeNotFoundError, match=UNKNOWN):
        _client(repo).node(UNKNOWN)
    with pytest.raises(ValueError):
        _client(repo).node("../../../etc/passwd")
    assert all("etc" not in request.url.path for request in repo.requests)


def test_a_node_is_read_without_the_credentials_of_the_client() -> None:
    """The endpoints have no login, so a node is read as the public sees it; collections keep the credentials."""
    repo = FakeRepository()
    client = _client(repo, user="redaktion", password="geheim")
    client.node(MATERIAL)
    assert "authorization" not in repo.requests[-1].headers
    client.collection(OPTIK)
    assert "authorization" in repo.requests[-1].headers, "part 3 reads collections as before"


def test_an_answer_without_a_node_is_a_repository_error() -> None:
    """A malformed answer is the repository's failure (502), not the service's (500)."""
    answer = httpx.MockTransport(lambda request: httpx.Response(200, json={"node": None}))
    with pytest.raises(EduSharingError, match="ohne Knoten"):
        EduSharingClient(BASE, transport=answer).node(MATERIAL)


def test_a_node_that_is_not_public_is_not_found() -> None:
    with pytest.raises(NodeNotFoundError, match="nicht öffentlich"):
        _client(FakeRepository()).node(PRIVATE)


@pytest.mark.parametrize(
    "value",
    [
        "https://repository.staging.openeduhub.net",
        "https://repository.staging.openeduhub.net/",
        "https://repository.staging.openeduhub.net/edu-sharing",
        "https://repository.staging.openeduhub.net/edu-sharing/rest",
        "https://repository.staging.openeduhub.net/edu-sharing/rest/",
        " https://Repository.Staging.OpenEduHub.net/edu-sharing/rest ",
    ],
)
def test_the_usual_spellings_of_a_repository_lead_to_its_rest_root(value: str) -> None:
    assert repository_root(value, ALLOWED) == STAGING


@pytest.mark.parametrize(
    "value",
    [
        "http://repository.staging.openeduhub.net/edu-sharing/rest",  # no TLS
        "https://example.org/edu-sharing/rest",  # not an allowed host
        "https://repository.staging.openeduhub.net.example.org/edu-sharing/rest",  # an allowed name as prefix only
        "https://user:secret@repository.staging.openeduhub.net/edu-sharing/rest",  # credentials in the address
        "https://repository.staging.openeduhub.net:8443/edu-sharing/rest",  # another port
        "https://repository.staging.openeduhub.net/edu-sharing/rest/node/v1",  # a path beyond the REST root
        "https://repository.staging.openeduhub.net/other",
        "https://repository.staging.openeduhub.net/edu-sharing/rest?x=1",
        "ftp://repository.staging.openeduhub.net/edu-sharing/rest",
        "",
        "https://[::1",  # addresses urlsplit itself cannot parse: refused, not a server error
        "https://[evil]/",
        "https://repository.staging.openeduhub.net]/",
        "https://a" + chr(0xFF03) + "@b/",  # a fullwidth number sign, invalid under NFKC
    ],
)
def test_an_address_that_could_reach_another_server_is_refused(value: str) -> None:
    with pytest.raises(RepositoryNotAllowedError):
        repository_root(value, ALLOWED)


def test_the_refusal_names_the_allowed_repositories() -> None:
    with pytest.raises(RepositoryNotAllowedError, match=re.escape("redaktion.openeduhub.net")):
        repository_root("https://example.org", ALLOWED)


def test_a_node_gives_its_title_as_topic_its_subject_and_levels_and_keywords_as_context() -> None:
    info = _client(FakeRepository()).node(MATERIAL)
    derived = node_topic(info)
    assert derived.topic == "Stationsarbeit zur Optik"
    assert derived.subjects == [BIOLOGIE, PHYSIK], "every subject of the node, all of equal weight"
    assert derived.context == ["Sekundarstufe I", *info.keywords], "the levels, then the keywords"


PHYSIK_OPTIK = NodeInfo(
    node_id=MATERIAL,
    kind="material",
    title="Physik: Optik",
    description="",
    keywords=("Linse",),
    subject_uris=(PHYSIK,),
    subject_labels=("Physik",),
    educational_contexts=("Sekundarstufe I",),
    url="",
)


def test_the_derived_topic_is_normalised_like_a_topic_sent_along() -> None:
    """One derivation for compendium, knowledge and the preview (D45): the preview shows what a request resolves."""
    found = derive_topic(None, [node_topic(PHYSIK_OPTIK)])
    assert found.normalized.topic == "Optik"
    assert found.subjects == ["Physik"], "a subject named in the title wins over the node's subjects"
    assert found.context == ["Fach Physik", "Sekundarstufe I", "Linse"]


def test_a_topic_and_a_subject_sent_along_win_over_the_node() -> None:
    found = derive_topic("Linse", [node_topic(PHYSIK_OPTIK)])
    assert found.normalized.topic == "Linse" and found.subjects == [PHYSIK]
    assert found.context == ["Sekundarstufe I", "Linse"], "the node still brings its levels and keywords"
    assert derive_topic("Linse", [node_topic(PHYSIK_OPTIK)], subject="Chemie").subjects == ["Chemie"]


def test_the_node_comes_before_the_collection() -> None:
    collection = CollectionTopic(
        topic="Optik", subjects=["http://w3id.org/openeduhub/vocabs/discipline/720"], context=["Sekundarstufe II"]
    )
    found = derive_topic(None, [node_topic(PHYSIK_OPTIK), collection])
    assert found.normalized.topic == "Optik" and found.subjects == ["Physik"]
    assert found.context == ["Fach Physik", "Sekundarstufe I", "Linse", "Sekundarstufe II"]


def test_the_builder_caches_a_node_per_repository(tmp_path: Path) -> None:
    repo, other = FakeRepository(), FakeRepository()
    cache = TtlCache(tmp_path / "wlo_cache.db")
    first = CollectionBuilder(client=_client(repo), cache=cache)
    elsewhere = EduSharingClient("https://other.test/edu-sharing/rest", transport=httpx.MockTransport(other))
    second = CollectionBuilder(client=elsewhere, cache=cache)
    assert first.node(MATERIAL) == first.node(MATERIAL)
    assert len(repo.requests) == 1, "the second read comes from the cache"
    assert isinstance(second.node(MATERIAL), NodeInfo)
    assert len(other.requests) == 1, "the same id in another repository is another node"
    assert BASE.startswith("https://repo.test")


def test_the_render_address_keeps_a_host_whose_name_starts_with_edu_sharing() -> None:
    root = "https://edu-sharing.example.org/edu-sharing/rest"
    expected = f"https://edu-sharing.example.org/edu-sharing/components/render/{MATERIAL}"
    assert EduSharingClient(root).render_url(MATERIAL) == expected
    assert node_input(_client(FakeRepository()).node(MATERIAL), root).render_url == expected


def test_the_node_keeps_the_id_it_was_asked_for() -> None:
    """The id of the answer is not checked; the id of the request is, so that one names the node."""
    answer = _fixture("node_material.json")
    del answer["node"]["ref"]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=answer))
    assert EduSharingClient(BASE, transport=transport).node(MATERIAL).node_id == MATERIAL


def test_keywords_come_trimmed_and_once() -> None:
    """They become context words and part of the entities text; a blank or a repeat adds nothing there."""
    answer = _fixture("node_material.json")
    keywords = [" Licht ", "Licht", "", "  ", "Linse", "Licht" + chr(10) + "strahl"]  # chr(10): a line break
    answer["node"]["properties"]["cclom:general_keyword"] = keywords
    assert parse_node(answer).keywords == ("Licht", "Linse", "Licht strahl")


def test_a_node_brings_all_its_subjects_before_those_of_a_collection() -> None:
    material = _client(FakeRepository()).node(MATERIAL)
    collection = CollectionTopic(topic="Optik", subjects=[PHYSIK], context=[])
    assert derive_topic("Linse", [node_topic(material), collection]).subjects == [BIOLOGIE, PHYSIK]
    assert derive_topic("Linse", [collection]).subjects == [PHYSIK]
