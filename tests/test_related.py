"""Link ranking blacklist: list articles and meta pages never enter a corpus."""

from app.domain.models import ArticleSection, Paragraph, Source
from app.knowledge.related import is_blacklisted, rank_related_candidates


def test_blacklist_covers_lists_meta_pages_and_umbrella_terms() -> None:
    assert is_blacklisted("Liste von Programmiersprachen")
    assert is_blacklisted("Kategorie:Optik")
    assert is_blacklisted("Physik")
    assert not is_blacklisted("Wellenoptik")
    assert not is_blacklisted("Geometrische Optik")


def test_a_topic_named_like_a_pattern_waives_that_pattern_only() -> None:
    # "Programmiersprache" matches the language pattern, and that once let every list and umbrella term in (M8)
    assert not is_blacklisted("Syntax (Programmiersprache)", topic="Programmiersprache")
    assert is_blacklisted("Liste von Programmiersprachen", topic="Programmiersprache")
    assert is_blacklisted("Physik", topic="Programmiersprache")


def test_the_links_of_a_topic_named_like_a_pattern_keep_lists_out() -> None:
    main = Source(
        source_id="wikipedia:Programmiersprache",
        project="wikipedia",
        title="Programmiersprache",
        url="https://de.wikipedia.org/wiki/Programmiersprache",
        sections=[ArticleSection(paragraphs=[Paragraph(text="Siehe Syntax (Programmiersprache) und Liste von …")])],
    )
    ranked = rank_related_candidates(main, ["Liste von Programmiersprachen", "Syntax (Programmiersprache)"])
    assert ranked == ["Syntax (Programmiersprache)"]
