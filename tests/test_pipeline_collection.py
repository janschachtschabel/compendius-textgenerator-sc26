"""Collections in the pipeline: topic from the collection, part 3 in the markdown, knowledge sources for part 1."""

from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.domain.requests import GenerateRequest
from app.service import CompendiumService, PartsUnavailableError
from app.settings import Settings
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import CollectionNotFoundError, EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from tests.test_lehrplan_api import write_cache
from tests.test_wlo_client import BASE, OPTIK, UNKNOWN, FakeRepository


@pytest.fixture
def with_collections(
    service: CompendiumService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[CompendiumService]:
    client = EduSharingClient(BASE, transport=httpx.MockTransport(FakeRepository()), page_size=10)
    builder = CollectionBuilder(client=client, cache=TtlCache(tmp_path / "wlo_cache.db"))
    monkeypatch.setattr(service, "collections", builder)
    yield service


def test_collection_gives_topic_subject_and_part_three(with_collections: CompendiumService) -> None:
    result = with_collections.generate(GenerateRequest(collection_id=OPTIK, parts=["world", "collection"]))
    assert result.topic == "Optik" and result.resolution.query == "Optik"
    assert result.collection is not None and result.collection.available
    assert result.collection.summary["materials"] == 16
    assert result.frontmatter["parts"] == ["world", "collection"]
    markdown = result.markdown
    assert markdown.index("## Teil 1 · Weltwissen") < markdown.index("## Teil 3 · Die Sammlung im Überblick")
    assert f"<!-- f: Sammlung={OPTIK}; Fach=Physik; Bildungsstufe=Sek I -->" in markdown
    assert result.audit.timings_ms["collection"] >= 0


def test_an_explicit_topic_wins_over_the_collection_title(with_collections: CompendiumService) -> None:
    request = GenerateRequest(topic="Photosynthese", collection_id=OPTIK, parts=["world", "collection"])
    result = with_collections.generate(request)
    assert result.topic == "Photosynthese"
    assert result.collection is not None and result.collection.title == "Optik"


def test_knowledge_collection_adds_reusable_material_sources(with_collections: CompendiumService) -> None:
    request = GenerateRequest(topic="Optik", knowledge_collection_id=OPTIK, parts=["world"])
    result = with_collections.generate(request)
    materials = [source for source in result.sources if source.project == "wlo_material"]
    assert materials
    assert all(source.license in {"CC0 1.0", "CC BY 4.0", "CC BY-SA 4.0"} for source in materials)
    assert result.audit.knowledge is not None
    assert result.audit.knowledge["sources"] == len(materials) and result.audit.knowledge["skipped_license"] == 8


def test_unknown_collection_is_reported(with_collections: CompendiumService) -> None:
    with pytest.raises(CollectionNotFoundError):
        with_collections.generate(GenerateRequest(collection_id=UNKNOWN))


def test_request_needs_a_topic_or_a_valid_collection_id() -> None:
    with pytest.raises(ValidationError):
        GenerateRequest()
    with pytest.raises(ValidationError):
        GenerateRequest(collection_id="not-a-uuid")
    assert GenerateRequest(collection_id=OPTIK).topic is None


def test_material_attribution_names_authors_and_the_exact_licences(with_collections: CompendiumService) -> None:
    request = GenerateRequest(topic="Optik", knowledge_collection_id=OPTIK, parts=["world"])
    result = with_collections.generate(request)
    sources_block = next(section.text for section in result.sections if section.slot_key == "quellen")
    assert "siehe Material" not in sources_block
    materials = [source for source in result.sources if source.project == "wlo_material"]
    assert any(source.authors for source in materials)
    for source in materials:
        named = ", ".join(source.authors) if source.authors else "nicht angegeben"
        assert f"Titel „{source.title}“ · Urheber {named} · Lizenz {source.license}" in sources_block
    note = sources_block[sources_block.index("Lizenz- und Attributionshinweis") :]
    for licence in {source.license for source in result.sources}:
        assert licence in note  # the note names what was actually used instead of claiming one licence for all


def test_a_capped_corpus_keeps_the_requested_materials_and_lists_only_used_sources(
    with_collections: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = GenerateRequest(topic="Optik", knowledge_collection_id=OPTIK, parts=["world"])
    full = with_collections.prepare(request)
    assert full.chunks_truncated == 0 and len(full.chunks) > 30
    monkeypatch.setattr(with_collections.settings, "corpus_max_chunks", 30)
    capped = with_collections.prepare(request)
    used = {chunk.source_id for chunk in capped.chunks}
    assert len(capped.chunks) == 30 and capped.chunks_truncated == len(full.chunks) - 30
    origins = {source.source_id: source.origin for source in full.sources}
    total = Counter(origins[chunk.source_id] for chunk in full.chunks)
    kept = Counter(origins[chunk.source_id] for chunk in capped.chunks)
    # The collection was asked for; it is not the first thing cut: linked and searched articles go before it
    assert kept["material"] and (kept["material"] == total["material"] or not kept["linked"] + kept["search"])
    assert all(source.source_id in used for source in capped.sources)  # no source listed without a paragraph
    assert with_collections.generate(request).audit.chunks_truncated == len(full.chunks) - 30


def test_the_request_deadline_stops_material_fetches(
    with_collections: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Spent:
        def __init__(self, seconds: float) -> None:
            self.seconds = seconds

        def remaining(self) -> float:
            return 0.0

    monkeypatch.setattr("app.service.Deadline", Spent)
    result = with_collections.generate(GenerateRequest(topic="Optik", knowledge_collection_id=OPTIK, parts=["world"]))
    knowledge = result.audit.knowledge
    assert knowledge is not None
    assert knowledge["timed_out"] == knowledge["considered"] > 0 and knowledge["sources"] == 0


def test_the_knowledge_collection_is_read_only_for_part_one(
    service: CompendiumService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = FakeRepository()
    client = EduSharingClient(BASE, transport=httpx.MockTransport(repository), page_size=10)
    monkeypatch.setattr(service, "collections", CollectionBuilder(client=client, cache=TtlCache(tmp_path / "c.db")))
    result = service.generate(GenerateRequest(topic="Optik", knowledge_collection_id=OPTIK, parts=["curricula"]))
    # The materials only feed part 1: without it, up to REQUEST_TIMEOUT_S of text reads would be thrown away
    assert result.audit.knowledge is None and repository.requests == []


def test_a_request_for_part_three_alone_needs_its_collection() -> None:
    with pytest.raises(ValidationError, match="collection_id"):
        GenerateRequest(topic="Optik", parts=["collection"])  # nothing could be generated: an empty 200 before
    assert GenerateRequest(topic="Optik").parts == ["world", "curricula", "collection"]  # part 3 simply drops out
    assert GenerateRequest(topic="Optik", parts=["world", "collection"]).collection_id is None


def test_part_three_alone_needs_no_article_in_the_archives(with_collections: CompendiumService) -> None:
    request = GenerateRequest(topic="Xyzzyplomb", collection_id=OPTIK, parts=["collection"])
    result = with_collections.generate(request)  # a TopicNotFoundError (404) before
    assert result.collection is not None and result.collection.available
    assert result.topic == "Xyzzyplomb" and result.resolution.title is None  # tried, not needed
    assert result.sources == [] and "corpus" not in result.audit.timings_ms  # no corpus built for nothing


def test_parts_this_service_cannot_make_are_refused_not_answered_empty(
    with_collections: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(with_collections, "curricula", None)  # a service without part 2
    with pytest.raises(PartsUnavailableError, match="collection_id"):  # was a compendium with parts: []
        with_collections.generate(GenerateRequest(topic="Optik", parts=["curricula", "collection"]))


def test_an_unconfigured_part_two_does_not_make_part_three_need_an_article(
    with_collections: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(with_collections, "curricula", None)
    request = GenerateRequest(topic="Xyzzyplomb", collection_id=OPTIK, parts=["curricula", "collection"])
    result = with_collections.generate(request)  # a TopicNotFoundError (404) before
    assert result.collection is not None and result.collection.available
    assert result.sources == [] and "corpus" not in result.audit.timings_ms


def test_part_three_keeps_to_the_time_budget_of_the_request(
    with_collections: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(with_collections.settings, "request_timeout_s", 0)  # spent before part 3 starts
    result = with_collections.generate(GenerateRequest(collection_id=OPTIK, parts=["collection"]))
    assert result.collection is not None and result.collection.available
    assert result.collection.summary["incomplete"] is True


def test_all_three_parts_land_in_one_markdown_in_order(with_collections: CompendiumService, settings: Settings) -> None:
    """The answer carries one document, not three: part 1 from the archives, part 2 from the curriculum cache
    and part 3 from the collection follow each other under a single frontmatter block and a single title."""
    write_cache(settings.state_dir)
    result = with_collections.generate(
        GenerateRequest(collection_id=OPTIK, parts=["world", "curricula", "collection"], subject="Physik")
    )
    assert result.frontmatter["parts"] == ["world", "curricula", "collection"]
    assert result.curricula is not None and result.collection is not None and result.collection.available

    markdown = result.markdown
    fences = [i for i, line in enumerate(markdown.split("\n")) if line == "---"]
    assert markdown.count("# Kompendium: Optik") == 1 and len(fences) == 2  # one title, one frontmatter
    assert fences[0] == 0
    world = markdown.index("## Teil 1 · Weltwissen")
    curricula = markdown.index("## Teil 2 · Lehrplanbezüge")
    collection = markdown.index("## Teil 3 · Die Sammlung im Überblick")
    assert world < curricula < collection
    assert "„Lichtbrechung an Linsen“ (Kompetenz)" in markdown[curricula:collection]
    part_three = markdown[collection:]
    # 16 own materials plus the same 16 under each of the four sub-collections: the repository double answers
    # every children/references path with the same two pages.
    contents = [line for line in part_three.split(chr(10)) if line.lstrip().startswith("- Inhalt: ")]
    assert len(contents) == 80 and all(" · nodeId: " in line for line in contents)  # one line per content, with its id
    assert "nodeId: 4bfa7693-0764-4dca-9720-c5fb0b8892d6" in part_three


def test_the_order_of_the_parts_is_the_documents_not_the_requests(
    with_collections: CompendiumService, settings: Settings
) -> None:
    """A caller may list ``parts`` in any order; the document keeps 1-2-3, and so does the frontmatter."""
    write_cache(settings.state_dir)
    result = with_collections.generate(
        GenerateRequest(collection_id=OPTIK, parts=["collection", "curricula", "world"], subject="Physik")
    )
    assert result.frontmatter["parts"] == ["world", "curricula", "collection"]
    markdown = result.markdown
    assert (
        markdown.index("## Teil 1 · Weltwissen")
        < markdown.index("## Teil 2 · Lehrplanbezüge")
        < markdown.index("## Teil 3 · Die Sammlung im Überblick")
    )
