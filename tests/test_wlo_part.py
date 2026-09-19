"""CollectionBuilder: cached repository reads, part 3 with sub-collection contents, knowledge sources, topic derivation."""

from pathlib import Path

import httpx
import pytest

from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import CollectionNotFoundError, EduSharingClient
from app.sources.wlo.part import CollectionBuilder, CollectionOptions, collection_topic
from tests.test_wlo_client import BASE, OPTIK, UNKNOWN, FakeRepository


def _builder(repo: FakeRepository, tmp_path: Path, **options: object) -> CollectionBuilder:
    client = EduSharingClient(BASE, transport=httpx.MockTransport(repo), page_size=10)
    return CollectionBuilder(
        client=client, cache=TtlCache(tmp_path / "wlo_cache.db"), options=CollectionOptions(**options)
    )  # type: ignore[arg-type]


def test_overview_reads_collection_materials_and_subcollection_contents_once(tmp_path: Path) -> None:
    repo = FakeRepository()
    builder = _builder(repo, tmp_path)
    part = builder.overview(OPTIK)
    assert part.available and part.collection_id == OPTIK and part.title == "Optik"
    assert part.markdown.startswith("## Teil 3 · Die Sammlung im Überblick")
    assert part.summary["materials"] == 16 and part.summary["subcollections"] == 4
    assert part.summary["subcollection_materials"]["Geometrische Optik"] == 16  # the fake serves one listing
    first_round = len(repo.requests)
    builder.overview(OPTIK)
    assert len(repo.requests) == first_round  # everything came from the cache


def test_unknown_collection_raises_and_topic_is_derived_from_the_collection(tmp_path: Path) -> None:
    builder = _builder(FakeRepository(), tmp_path)
    with pytest.raises(CollectionNotFoundError):
        builder.overview(UNKNOWN)
    topic = collection_topic(builder.info(OPTIK))
    assert topic.topic == "Optik"
    assert topic.subject == "http://w3id.org/openeduhub/vocabs/discipline/460"
    assert topic.context == ["Sekundarstufe I"]


def test_knowledge_sources_follow_the_licence_policy_and_report_gaps(tmp_path: Path) -> None:
    result = _builder(FakeRepository(), tmp_path).knowledge_sources(OPTIK)
    # 16 materials: 8 under CC0/CC BY/CC BY-SA, of which the fixture has text for a few
    assert result.considered == 8 and result.skipped_license == 8
    assert result.failed == []
    assert all(source.project == "wlo_material" for source in result.sources)
    assert {source.title for source in result.sources} >= {"Unterrichtsreihe zum Licht"}
    assert result.empty == result.considered - len(result.sources)


def test_the_knowledge_listing_ends_when_the_time_is_up_and_is_not_kept(tmp_path: Path) -> None:
    repo = FakeRepository()
    builder = _builder(repo, tmp_path)

    def listings() -> int:
        return sum(request.url.path.endswith("/children/references") for request in repo.requests)

    result = builder.knowledge_sources(OPTIK, expired=lambda: listings() >= 1)  # the budget ends after one page
    assert listings() == 1  # a large collection could take 200 pages outside the request's time budget
    assert result.timed_out == result.considered  # no text is read after the time is up either
    builder.references(OPTIK)
    assert listings() == 3  # the cut listing was not kept for an hour: the next read lists both pages again
