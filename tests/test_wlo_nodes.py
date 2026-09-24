"""A node of an edu-sharing repository as input (D45): its metadata, the repository address, the derived topic.

A material or a collection comes with title, description, keywords, subject and educational level; the service
reads them from ``/node/v1/nodes/-home-/{id}/metadata``. The repository a request names is caller input, so only
https addresses of allowed hosts pass, and the path is always the REST root - nothing else of the address counts.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient, NodeNotFoundError
from app.sources.wlo.models import NodeInfo
from app.sources.wlo.part import CollectionBuilder, node_topic
from app.sources.wlo.repository import RepositoryNotAllowedError, repository_root
from tests.test_wlo_client import BASE, MATERIAL, OPTIK, UNKNOWN, FakeRepository, _client

STAGING = "https://repository.staging.openeduhub.net/edu-sharing/rest"
ALLOWED = frozenset({"repository.staging.openeduhub.net", "redaktion.openeduhub.net"})
PHYSIK = "http://w3id.org/openeduhub/vocabs/discipline/460"


def test_a_material_node_gives_title_description_keywords_subject_and_level() -> None:
    info = _client(FakeRepository()).node(MATERIAL)
    assert info.node_id == MATERIAL and info.kind == "material"
    assert info.title == "Stationsarbeit zur Optik"
    assert info.description.startswith("An sechs Stationen untersuchen Lernende")
    assert info.keywords == ("Auge", "Netzhaut", "Pupille", "Linse", "Lochkamera")
    assert info.subject_uris == (PHYSIK,) and info.subject_labels == ("Physik",)
    assert info.educational_contexts == ("Sekundarstufe I",)
    assert info.url == "https://example.org/stationsarbeit-optik"


def test_a_collection_node_reads_the_same_way_and_says_what_it_is() -> None:
    info = _client(FakeRepository()).node(OPTIK)
    assert info.kind == "collection" and info.title == "Optik"
    assert "Linse" in info.keywords and info.subject_labels == ("Physik",)
    assert info.description.startswith("Die Physik des Lichts")


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
    assert derived.subject == PHYSIK
    assert derived.context == ["Sekundarstufe I", "Auge", "Netzhaut", "Pupille", "Linse", "Lochkamera"]


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
