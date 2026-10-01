"""CollectionBuilder: cached repository reads, part 3 with sub-collection contents, knowledge sources, topic derivation."""

import dataclasses
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import CollectionNotFoundError, EduSharingClient, Remaining
from app.sources.wlo.errors import TimeUpError
from app.sources.wlo.knowledge import KnowledgeOptions
from app.sources.wlo.models import MaterialRef, SubCollection
from app.sources.wlo.part import CollectionBuilder, CollectionOptions, _hydrate, collection_topic
from tests.test_wlo_client import BASE, OPTIK, UNKNOWN, FakeRepository


def _builder(repo: FakeRepository, tmp_path: Path, **options: Any) -> CollectionBuilder:
    client = EduSharingClient(BASE, transport=httpx.MockTransport(repo), page_size=10)
    return CollectionBuilder(
        client=client, cache=TtlCache(tmp_path / "wlo_cache.db"), options=CollectionOptions(**options)
    )


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
    assert topic.subjects == ["http://w3id.org/openeduhub/vocabs/discipline/460"]
    assert topic.context == ["Sekundarstufe I"]


def test_knowledge_sources_take_every_material_and_report_gaps(tmp_path: Path) -> None:
    """D70: no licence keeps a material out; with the full texts asked for, each is read."""
    result = _builder(FakeRepository(), tmp_path).knowledge_sources(OPTIK, fulltext=True)
    assert result.considered == 16 and result.failed == []  # all 16 materials, whatever their licence
    assert all(source.project == "wlo_material" for source in result.sources)
    assert {source.title for source in result.sources} >= {"Unterrichtsreihe zum Licht"}
    assert result.empty == result.considered - len(result.sources)


def test_knowledge_depth_reads_the_subcollections_once_each(tmp_path: Path) -> None:
    """D70 (Jan: by default the collection's own contents, with knowledge_depth those of its sub-collections, down to
    that depth). The fake gives every collection the same four sub-collections: each is read once, a material once."""
    repo = FakeRepository()
    builder = _builder(repo, tmp_path)

    def listed() -> set[str]:
        return {r.url.path.split("/")[-3] for r in repo.requests if r.url.path.endswith("/children/references")}

    alone = builder.knowledge_sources(OPTIK)
    assert listed() == {OPTIK} and alone.collections == 1
    deep = builder.knowledge_sources(OPTIK, depth=2)
    subs = {sub.id for sub in builder.subcollections(OPTIK)}
    assert listed() == {OPTIK, *subs} and deep.collections == 5
    assert len({source.source_id for source in deep.sources}) == len(deep.sources)


_TREE_MATERIALS = {"root": 10, "a": 3, "b": 3}


class _Tree(CollectionBuilder):
    """A root with many materials of its own and two sub-collections with a few each."""

    def references(self, collection_id: str, *, remaining: Remaining | None = None) -> list[MaterialRef]:
        return [_material(f"{collection_id}-{n}") for n in range(_TREE_MATERIALS[collection_id])]

    def subcollections(self, collection_id: str, *, remaining: Remaining | None = None) -> list[SubCollection]:
        subs = ["a", "b"] if collection_id == "root" else []
        return [SubCollection(id=sub, title=sub, description="") for sub in subs]


def _material(material_id: str) -> MaterialRef:
    description = f"Beschreibung des Materials {material_id}, lang genug für eine Quelle."
    return MaterialRef(
        id=material_id,
        title=material_id,
        description=description,
        url="",
        original_id=None,
        license_key="",
        mimetype=None,
        keywords=(),
        resource_types=(),
        educational_contexts=(),
        subjects=(),
        subject_uris=(),
    )


def test_knowledge_depth_takes_the_collections_in_turn_so_the_cap_leaves_none_out() -> None:
    """D70: a large collection filled KNOWLEDGE_MAX_MATERIALS before a sub-collection came (staging Optik: 168
    materials, the cap 30, depth 1 added nothing); taken in turn, every collection read brings materials."""
    client = EduSharingClient(BASE, transport=httpx.MockTransport(FakeRepository()))
    options = CollectionOptions(knowledge=KnowledgeOptions(max_materials=6))
    tree = _Tree(client=client, cache=None, options=options)

    alone = tree.knowledge_sources("root")
    deep = tree.knowledge_sources("root", depth=1)

    assert [source.title for source in alone.sources] == [f"root-{n}" for n in range(6)]
    assert [source.title for source in deep.sources] == ["root-0", "a-0", "b-0", "root-1", "a-1", "b-1"]
    assert deep.collections == 3


def test_the_knowledge_listing_ends_when_the_time_is_up_and_is_not_kept(tmp_path: Path) -> None:
    repo = FakeRepository()
    builder = _builder(repo, tmp_path)

    def listings() -> int:
        return sum(request.url.path.endswith("/children/references") for request in repo.requests)

    def remaining() -> float:  # the budget ends after one page
        return 0.0 if listings() >= 1 else 60.0

    result = builder.knowledge_sources(OPTIK, remaining=remaining, fulltext=True)
    assert listings() == 1  # a large collection could take 200 pages outside the request's time budget
    assert result.timed_out == result.considered  # no text is read after the time is up either
    builder.references(OPTIK)
    assert listings() == 3  # the cut listing was not kept for an hour: the next read lists both pages again


def test_the_overview_stops_listing_when_the_time_is_up_and_says_so(tmp_path: Path) -> None:
    repo = FakeRepository()
    builder = _builder(repo, tmp_path)

    def listings() -> int:
        return sum(request.url.path.endswith("/children/references") for request in repo.requests)

    def remaining() -> float:  # the budget ends after the first page
        return 0.0 if listings() >= 1 else 60.0

    part = builder.overview(OPTIK, remaining=remaining)
    assert listings() == 1  # neither the second page nor the materials of the four sub-collections
    assert part.available and part.summary["incomplete"] is True and part.summary["subcollections"] == 4
    assert set(part.summary["subcollection_materials"].values()) == {0}
    assert "möglicherweise unvollständig" in part.markdown
    (tmp_path / "b").mkdir()
    complete = _builder(FakeRepository(), tmp_path / "b").overview(OPTIK)
    assert complete.summary["incomplete"] is False and "unvollständig" not in complete.markdown


def _spent() -> float:
    return 0.0


def test_a_spent_budget_asks_the_repository_nothing(tmp_path: Path) -> None:
    """overview(…, expired=lambda: True) still read the collection, a page of its materials and its sub-collections,
    each with the full client timeout (audit 2026-09-29, A06); what the cache holds still counts."""
    repo = FakeRepository()
    builder = _builder(repo, tmp_path)
    with pytest.raises(TimeUpError):
        builder.overview(OPTIK, remaining=_spent)  # without the collection there is no part 3 to speak of
    with pytest.raises(TimeUpError):
        builder.knowledge_sources(OPTIK, remaining=_spent)  # an empty list would read as an empty collection
    assert repo.requests == []
    builder.info(OPTIK)  # as the service reads it at the start of a request, for the topic
    part = builder.overview(OPTIK, remaining=_spent)
    assert len(repo.requests) == 1
    assert not part.available and part.title == "Optik" and part.error == "Zeitbudget der Anfrage erschöpft"
    assert "Zeitbudget der Anfrage erschöpft" in part.markdown


def test_no_request_of_part_three_or_the_knowledge_waits_longer_than_the_time_left(tmp_path: Path) -> None:
    repo = FakeRepository()
    builder = _builder(repo, tmp_path)
    assert builder.overview(OPTIK, remaining=lambda: 2.5).available
    assert builder.knowledge_sources(OPTIK, remaining=lambda: 2.5, fulltext=True).sources
    timeouts = {value for request in repo.requests for value in request.extensions["timeout"].values()}
    assert timeouts == {2.5} and any(request.url.path.endswith("/textContent") for request in repo.requests)


def _without_attribution(ref: MaterialRef) -> dict[str, object]:
    """A listing entry as the version before license_version and authors wrote it."""
    return {key: value for key, value in dataclasses.asdict(ref).items() if key not in {"license_version", "authors"}}


def test_listings_cached_by_an_earlier_version_are_read_again(tmp_path: Path) -> None:
    repo = FakeRepository()
    builder = _builder(repo, tmp_path)
    earlier = [_without_attribution(ref) for ref in builder.client.references(OPTIK)]
    assert builder.cache is not None
    builder.cache.set(f"references:{OPTIK}", earlier, ttl_s=3600)  # written just before the deploy
    # Reusing it would print "Urheber nicht angegeben" for every material for up to an hour
    assert any(ref.authors for ref in builder.references(OPTIK))


def test_a_cached_record_without_newer_fields_gets_their_defaults(tmp_path: Path) -> None:
    ref = _builder(FakeRepository(), tmp_path).client.references(OPTIK)[0]
    hydrated = _hydrate(MaterialRef, _without_attribution(ref))
    assert hydrated.authors == () and hydrated.license_version == ""
    assert hydrated.keywords == ref.keywords and isinstance(hydrated.keywords, tuple)  # lists come back as tuples


SUB = "11111111-1111-4111-8111-111111111111"
MATERIAL = "ac66224b-42b0-4676-a53d-71b058dc780b"


def _repository(name: str) -> tuple[list[httpx.Request], httpx.MockTransport]:
    """A repository whose collection OPTIK, its listings, the material in it and its text all carry ``name``."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        named = {"cm:title": [name], "ccm:commonlicense_key": ["CC_BY"]}
        if path.endswith("/children/references"):
            return httpx.Response(200, json={"references": [{"ref": {"id": MATERIAL}, "properties": named}]})
        if path.endswith("/children/collections"):
            return httpx.Response(200, json={"collections": [{"ref": {"id": SUB}, "properties": named}]})
        if path.endswith("/textContent"):
            return httpx.Response(200, json={"text": f"Dieser Materialtext stammt aus dem Repository {name}."})
        if path.endswith("/metadata"):
            return httpx.Response(200, json={"node": {"ref": {"id": MATERIAL}, "properties": named}})
        return httpx.Response(200, json={"collection": {"ref": {"id": OPTIK}, "properties": named}})

    return requests, httpx.MockTransport(answer)


def _reads(builder: CollectionBuilder) -> dict[str, object]:
    """What each cached read of the builder gives for OPTIK and its material, by the name its repository wrote in."""
    texts = [
        paragraph.text
        for source in builder.knowledge_sources(OPTIK, fulltext=True).sources
        for section in source.sections
        for paragraph in section.paragraphs
    ]
    return {
        "info": builder.info(OPTIK).title,
        "references": [ref.title for ref in builder.references(OPTIK)],
        "subcollections": [sub.title for sub in builder.subcollections(OPTIK)],
        "node": builder.node(MATERIAL).title,
        "text": [text.rsplit(" ", 1)[-1] for text in texts],
    }


def _expected(name: str) -> dict[str, object]:
    return {"info": name, "references": [name], "subcollections": [name], "node": name, "text": [f"{name}."]}


def test_the_same_ids_in_two_repositories_are_two_records_in_one_cache(tmp_path: Path) -> None:
    """Staging and production share node ids where one holds a copy of the other; only the key of a node named the
    host, so a collection, its listings and the texts of its materials read in one came back for the other - for an
    hour, the texts for a week (audit 2026-09-29, A03)."""
    cache = TtlCache(tmp_path / "wlo_cache.db")
    for name in ("staging", "produktion"):
        requests, transport = _repository(name)
        client = EduSharingClient(f"https://{name}.test/edu-sharing/rest", transport=transport)
        builder = CollectionBuilder(client=client, cache=cache)
        assert _reads(builder) == _expected(name)
        assert _reads(builder) == _expected(name) and len(requests) == 5, "the second round comes from the cache"


def test_another_account_does_not_get_what_the_first_one_read(tmp_path: Path) -> None:
    """Two accounts may see different things; a node is read without one (A02), so every account shares it."""
    cache = TtlCache(tmp_path / "wlo_cache.db")
    for user in ("", "redaktion", "lektorat"):
        _, transport = _repository(user or "anonym")
        client = EduSharingClient(BASE, user=user, password="geheim-4711", transport=transport)
        builder = CollectionBuilder(client=client, cache=cache)
        assert _reads(builder) == {**_expected(user or "anonym"), "node": "anonym"}
    with closing(sqlite3.connect(tmp_path / "wlo_cache.db")) as connection:
        keys = [row[0] for row in connection.execute("SELECT key FROM cache")]
    assert len(keys) == 13, keys  # four records and a text per context, the node once
    assert not [key for key in keys if "redaktion" in key or "lektorat" in key or "geheim" in key]


@pytest.mark.parametrize(
    ("other", "shared"),
    [
        ("https://repo.test/edu-sharing/rest/", True),
        ("HTTPS://Repo.TEST/edu-sharing/rest", True),
        ("https://repo.test:443/edu-sharing/rest", True),
        ("https://repo.test:8443/edu-sharing/rest", False),
        ("http://repo.test/edu-sharing/rest", False),
        ("https://repo.test/Edu-Sharing/rest", False),
        # a port httpx takes and only a real request refuses: reading it for the key must not stop the start
        ("https://repo.test:99999/edu-sharing/rest", False),
    ],
)
def test_the_cache_knows_a_repository_by_its_rest_root_however_it_is_written(
    tmp_path: Path, other: str, shared: bool
) -> None:
    cache = TtlCache(tmp_path / "wlo_cache.db")
    _, first = _repository("repo")
    CollectionBuilder(client=EduSharingClient(BASE, transport=first), cache=cache).info(OPTIK)
    requests, second = _repository("other")
    title = CollectionBuilder(client=EduSharingClient(other, transport=second), cache=cache).info(OPTIK).title
    assert (title, len(requests)) == (("repo", 0) if shared else ("other", 1))
