"""Whether two articles link to one another (M24, M25): the test the corpus puts extra articles to.

M24 measured on the corpora of real materials that an extra article is far more often unfit when neither it nor the
main article links to the other. Links are compared as the archive names their targets after a redirect, so a link
to "Strahlenoptik" counts as one to "Geometrische Optik".
"""

from __future__ import annotations

import gc
import weakref
from pathlib import Path

import pytest

from app.service import CompendiumService
from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import LinkedTo, ZimRegistry


def _source(registry: ZimRegistry, title: str):  # type: ignore[no-untyped-def]
    archive = registry.primary_archive
    assert archive is not None
    article = archive.read(title)
    assert article is not None, title
    return archive.to_source(article, is_primary=False)


def test_a_redirect_is_followed_to_the_title_of_its_article(registry: ZimRegistry) -> None:
    archive = registry.primary_archive
    assert archive is not None
    assert archive.canonical_title("Strahlenoptik") == "Geometrische Optik"
    assert archive.canonical_title("Optik") == "Optik"
    assert archive.canonical_title("Kein Artikel dieses Namens") is None


def test_two_articles_are_linked_when_either_links_to_the_other(registry: ZimRegistry) -> None:
    archive = registry.primary_archive
    assert archive is not None
    optik, brechung = _source(registry, "Optik"), _source(registry, "Brechung (Physik)")
    assert LinkedTo(archive, optik)(brechung), "Optik links to Brechung (Physik)"
    assert LinkedTo(archive, brechung)(optik), "the order of the two does not matter"


def test_a_link_through_a_redirect_counts(registry: ZimRegistry) -> None:
    archive = registry.primary_archive
    assert archive is not None
    geometrische, brechung = _source(registry, "Geometrische Optik"), _source(registry, "Brechung (Physik)")
    assert LinkedTo(archive, geometrische)(brechung), "Brechung (Physik) links to the redirect Strahlenoptik"


def test_articles_without_a_link_between_them_are_not_linked(registry: ZimRegistry) -> None:
    archive = registry.primary_archive
    assert archive is not None
    assert not LinkedTo(archive, _source(registry, "Optik"))(_source(registry, "Programmiersprache"))


def test_a_repeated_topic_takes_the_resolved_links_from_the_archive(
    registry: ZimRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolving the links of Deutschland took 1.9 s in a first corpus and 0.19 s in a second one on the same topic."""
    archive = registry.primary_archive
    assert archive is not None
    optik, programmiersprache = _source(registry, "Optik"), _source(registry, "Programmiersprache")
    assert not LinkedTo(archive, optik)(programmiersprache)  # no link either way: the links of both get resolved
    lookups: list[str] = []
    entry = archive._entry

    def spy(identifier: str) -> object:
        lookups.append(identifier)
        return entry(identifier)

    monkeypatch.setattr(archive, "_entry", spy)
    assert not LinkedTo(archive, optik)(programmiersprache)
    assert lookups == [], "a name resolved once, to an article or to nothing, is not looked up again"


def test_an_archive_nobody_uses_any_more_is_closed_at_once(sample_zims: dict[str, Path]) -> None:
    """The ZIM sync opens an archive only to read its metadata and later deletes replaced files: a cache that points
    back at its archive kept the file open until a garbage collection, and Windows refused to delete it."""
    archive = ZimArchive(sample_zims["wikipedia"])
    assert archive.canonical_title("Strahlenoptik") == "Geometrische Optik"
    alive = weakref.ref(archive)
    gc.disable()  # a reference cycle must not go unnoticed because a collection happened to run
    try:
        del archive
        assert alive() is None
    finally:
        gc.enable()


def test_a_full_text_hit_without_a_link_either_way_stays_out_of_the_corpus(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M25: of 16 hits without a link on the term gold, 10 were unfit; leaving them out halved the unfit paragraphs.

    The sample archive has no such hit of its own, so the full-text index answers with one here; reading the articles
    and checking their links is real.
    """
    registry = service.registry
    archive = registry.primary_archive
    assert archive is not None
    monkeypatch.setattr(archive, "search", lambda query, limit=10: ["Schutz vor optischer Strahlung", "Lichtmikroskop"])
    slots = service.templates.get(service.settings.template_default).content_slots()
    corpus = registry.build_corpus(registry.resolve_topic("Optik"), slots=slots, max_articles=30)
    origins = {source.title: source.origin for source in corpus}
    assert origins["Lichtmikroskop"] == "search", "it links to Optik"
    assert "Schutz vor optischer Strahlung" not in origins, "neither it nor Optik links to the other"


def test_the_article_of_a_material_joins_only_when_it_links_with_the_main_article(service: CompendiumService) -> None:
    """D47: the material's own article beside a topic sent along; unlinked it stays out, like an unlinked hit."""
    registry = service.registry
    slots = service.templates.get(service.settings.template_default).content_slots()
    unlinked = registry.build_corpus(registry.resolve_topic("Programmiersprache"), slots, 30, material="Optik")
    assert [source.title for source in unlinked] == ["Programmiersprache"]
    linked = registry.build_corpus(registry.resolve_topic("Geometrische Optik"), slots, 30, material="Optik")
    assert {source.title: source.origin for source in linked}["Optik"] == "node"


def test_a_material_article_already_linked_in_the_corpus_becomes_the_node_article(service: CompendiumService) -> None:
    """It keeps its place and loses the topic filter of linked articles: the request asked for it."""
    registry = service.registry
    slots = service.templates.get(service.settings.template_default).content_slots()
    corpus = registry.build_corpus(registry.resolve_topic("Optik"), slots, 30, material="Geometrische Optik")
    assert ("Geometrische Optik", "node") in [(source.title, source.origin) for source in corpus]
    keys = [(source.project, source.title) for source in corpus]
    assert len(keys) == len(set(keys)), "it is not added a second time"


def test_the_article_of_a_material_joins_even_when_the_search_read_it_first(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The search reads a hit and drops it for lacking the topic in title and lead; the material's article stays due.

    Found in the review of M25 on the real Wikipedia: "Geometrische Optik" with "Linse (Optik)", "Photosynthese"
    with "Organell" - linked with the main article, yet missing from the corpus.
    """
    registry = service.registry
    archive = registry.primary_archive
    assert archive is not None
    monkeypatch.setattr(archive, "search", lambda query, limit=10: ["Brechung (Physik)"])
    slots = service.templates.get(service.settings.template_default).content_slots()
    resolution = registry.resolve_topic("Geometrische Optik")
    corpus = registry.build_corpus(resolution, slots, 30, material="Brechung (Physik)")
    assert {source.title: source.origin for source in corpus}.get("Brechung (Physik)") == "node"
