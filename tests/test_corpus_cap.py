"""CORPUS_MAX_CHUNKS: the ranks of ORIGIN_PRIORITY keep their order, the sources of one rank share what is left.

Audit 2026-10-02, A04: the cap was filled source by source, so the first side article took all that the topic's own
articles left. Measured in the dev container (llm-free, 2026-10-03): for "Deutschland" "Geschichte Deutschlands" kept
100 paragraphs and the six other linked articles none, among them those on its geography, climate and education.
"""

from __future__ import annotations

from collections import Counter

from app.compendium.corpus import segment_corpus
from app.domain.models import ArticleSection, Paragraph, Source
from app.matching.lexicon import HeadingLexicon


def _source(title: str, count: int, origin: str) -> Source:
    paragraphs = [
        Paragraph(text=f"Absatz {n} über {title} beschreibt die Entwicklung und die Zusammenhänge ausführlich.")
        for n in range(count)
    ]
    return Source(
        source_id=title,
        project="wikipedia",
        title=title,
        url=f"https://de.wikipedia.org/wiki/{title}",
        is_primary=origin == "primary",
        origin=origin,
        sections=[ArticleSection(heading="Geschichte", path=["Geschichte"], level=2, paragraphs=paragraphs)],
    )


def test_the_side_articles_of_one_rank_share_what_the_main_article_leaves() -> None:
    primary = _source("Optik", 300, "primary")
    sides = [_source(f"Optik {n}", 50, "linked") for n in range(1, 9)]

    chunks, kept, cut = segment_corpus([primary, *sides], HeadingLexicon.empty(), 400)

    taken = Counter(chunk.source_id for chunk in chunks)
    assert taken["Optik"] == 300  # the topic's own article first, as before
    assert [taken[side.source_id] for side in sides] == [12, 12, 12, 12, 13, 13, 13, 13]
    assert len(kept) == 9 and len(chunks) == 400 and cut == 300


def test_a_source_that_needs_less_than_its_share_leaves_the_rest_to_the_others() -> None:
    primary = _source("Optik", 300, "primary")
    small, first, second = (
        _source("Optik klein", 5, "linked"),
        _source("Optik A", 50, "linked"),
        _source("Optik B", 50, "linked"),
    )

    chunks, _, _ = segment_corpus([primary, first, small, second], HeadingLexicon.empty(), 400)

    taken = Counter(chunk.source_id for chunk in chunks)
    assert (taken["Optik klein"], taken["Optik A"], taken["Optik B"]) == (5, 47, 48)


def test_a_lower_rank_still_gets_only_what_the_higher_ones_leave() -> None:
    primary = _source("Optik", 300, "primary")
    linked = [_source(f"Optik {n}", 60, "linked") for n in range(1, 3)]
    hit = _source("Optik Treffer", 20, "search")

    chunks, kept, _ = segment_corpus([primary, *linked, hit], HeadingLexicon.empty(), 400)

    taken = Counter(chunk.source_id for chunk in chunks)
    assert [taken[source.source_id] for source in linked] == [50, 50] and taken["Optik Treffer"] == 0
    assert hit not in kept


def test_without_the_cap_biting_every_source_keeps_all_its_paragraphs() -> None:
    sources = [_source("Optik", 30, "primary"), *[_source(f"Optik {n}", 10, "linked") for n in range(1, 4)]]

    chunks, kept, cut = segment_corpus(sources, HeadingLexicon.empty(), 400)

    assert len(chunks) == 60 and len(kept) == 4 and cut == 0
    assert [chunk.source_id for chunk in chunks][:30] == ["Optik"] * 30  # the corpus order stays
