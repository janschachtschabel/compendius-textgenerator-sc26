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


def test_a_leading_article_of_the_title_boosts_no_link() -> None:
    """KO-11: the word "eine" of "Eine kleine Nachtmusik" was a stem of its own and lifted every link holding it."""
    main = Source(
        source_id="wikipedia:Eine kleine Nachtmusik",
        project="wikipedia",
        title="Eine kleine Nachtmusik",
        url="https://de.wikipedia.org/wiki/Eine_kleine_Nachtmusik",
        sections=[ArticleSection(paragraphs=[Paragraph(text="Ein Werk von Mozart.")])],
    )
    ranked = rank_related_candidates(main, ["Serenade", "Steinerne Brücke"])
    assert ranked == ["Serenade", "Steinerne Brücke"]  # neither holds a word of the topic: they keep their order
