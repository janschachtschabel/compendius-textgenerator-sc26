"""Linking, ranking and caching stay within bounds however large the articles (audit 2026-09-28, PE-04, PE-06, PE-07).

/entities read, parsed and copied every article it linked, up to 200, with no deadline: 6 to 19 s of CPU per request
without an LLM. The ranking of the linked articles counted the mentions of each link with a pattern of its own, and a
page with 8,000 links took 2 s. The parse cache kept 256 articles whatever their size.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v2.entities import _link
from app.domain.models import ArticleSection, Paragraph, Source
from app.knowledge.recognise import Mention
from app.knowledge.related import rank_related_candidates
from app.main import create_app
from app.settings import Settings
from app.sources.zim import archive as archive_module
from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import ZimRegistry

TEXT = "Ernst Abbe entwickelte in Jena das Lichtmikroskop und die Geometrische Optik."


def test_linking_stops_when_the_request_has_no_time_left(settings: Settings) -> None:
    client = TestClient(create_app(settings.model_copy(update={"request_timeout_s": 0})))

    body = client.post("/api/v2/entities", json={"text": TEXT}).json()

    assert {entity["text"] for entity in body["entities"]} >= {"Lichtmikroskop", "Geometrische Optik"}  # not dropped
    assert all(entity["linked"] is False for entity in body["entities"])
    assert "Zeitbudget" in body["note"]


def test_a_linked_article_is_read_for_its_lead_without_copying_it_whole(
    registry: ZimRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def whole(*args: object, **kwargs: object) -> None:
        raise AssertionError("the whole article was copied")

    monkeypatch.setattr(ZimArchive, "to_source", whole)

    article = _link(registry.archives, Mention("Ernst Abbe", 0, 10, "PER", "ner"))

    assert article is not None and article.kind == "Person" and 0 < len(article.lead) <= 400


def test_the_mentions_of_a_link_are_counted_as_before() -> None:
    """The count changed its means, not its result: this ranking is the one the pattern per link gave."""
    text = "Die Optik und die optik der Linsen; aaaa aa a. Linse, Linsen, Linsenfernrohr. Licht Lichtmikroskop Licht."
    main = Source(
        source_id="wikipedia:X",
        project="wikipedia",
        title="Beispiel",
        url="https://de.wikipedia.org/wiki/Beispiel",
        sections=[ArticleSection(heading="", path=[], level=0, paragraphs=[Paragraph(text=text)])],
    )
    candidates = ["Optik", "Linse", "aa", "Licht", "Lichtmikroskop", "Fernrohr", "Brille"]

    assert rank_related_candidates(main, candidates) == [
        "Linse",
        "Licht",
        "Optik",
        "Lichtmikroskop",
        "Fernrohr",
        "Brille",
    ]


def test_the_parse_cache_keeps_a_bounded_amount_of_text(
    sample_zims: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = ZimArchive(sample_zims["wikipedia"])
    articles = [archive.read(title) for title in ("Optik", "Geometrische Optik", "Lichtmikroskop")]
    assert all(article is not None for article in articles)
    sizes = [len(article.html) for article in articles if article is not None]
    monkeypatch.setattr(archive_module, "PARSE_CACHE_CHARS", sizes[1] + sizes[2])

    for article in articles:
        assert article is not None
        archive.parse(article)

    kept = list(archive._cache)  # the cache is what is measured
    assert kept == [articles[1].path, articles[2].path]  # type: ignore[union-attr]
