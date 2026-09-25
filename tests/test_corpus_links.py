"""Whether two articles link to one another (M24, M25): the test the corpus puts extra articles to.

M24 measured on the corpora of real materials that an extra article is far more often unfit when neither it nor the
main article links to the other. Links are compared as the archive names their targets after a redirect, so a link
to "Strahlenoptik" counts as one to "Geometrische Optik".
"""

from __future__ import annotations

import pytest

from app.service import CompendiumService
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
