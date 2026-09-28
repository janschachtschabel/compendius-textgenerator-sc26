"""A topic of a short word is found as a word with its endings, not inside other words (audit 2026-09-28, KO-29).

A title word of at most four letters is its own stem, and the checks that a side article or a paragraph is about the
topic looked for it inside any word: "ei" is inside "ein" and "bei". In 979 paragraphs of five foreign articles of the
German Wikipedia it found the topic Ei 862 times, Eis 313, Rad 93 and Ton 62 times; as a word with its endings 0, 10
("Eisen"), 0 and 0 times (measured 2026-09-28).
"""

from __future__ import annotations

from app.compendium.corpus import segment_corpus, subtopics
from app.domain.models import ArticleSection, Paragraph, Source, primary_of
from app.knowledge.topic import TopicMention
from app.matching.lexicon import HeadingLexicon


def _source(title: str, paragraphs: list[str], origin: str = "linked") -> Source:
    return Source(
        source_id=f"wikipedia:{title}",
        project="wikipedia",
        title=title,
        url=f"https://de.wikipedia.org/wiki/{title}",
        is_primary=origin == "primary",
        origin=origin,
        sections=[ArticleSection(heading="", path=[], level=0, paragraphs=[Paragraph(text=p) for p in paragraphs])],
    )


def test_a_short_title_word_is_a_word_with_its_endings() -> None:
    egg, eye, ice = TopicMention.of("Ei"), TopicMention.of("Auge"), TopicMention.of("Eis (Wasser)")

    assert not egg.found_in("Bei Tag ist ein Beispiel eines Kreises zu sehen.")
    assert egg.found_in("Das Huhn legt ein Ei.") and egg.found_in("Die Eier liegen im Nest.")
    assert eye.found_in("Beide Augen sehen scharf.") and not eye.found_in("Im Augenblick nicht.")
    assert ice.found_in("Die Dichte des Eises.") and not ice.found_in("Ein Kreis auf der Reise.")


def test_a_longer_stem_is_still_found_inside_words() -> None:
    """Sub-articles such as "Wellenoptik" carry the topic inside a word; the gold topics all have such stems."""
    assert TopicMention.of("Optik").found_in("Die Wellenoptik und optische Geräte")
    assert TopicMention.of("Die Zauberflöte").found_in("Mozarts Zauberflöten-Ouvertüre")
    assert not TopicMention.of("").found_in("irgendein Text")


def test_a_side_article_keeps_only_the_paragraphs_that_name_the_short_topic() -> None:
    primary = _source(
        "Ei", ["Ein Ei ist eine Keimzelle mit Schale und Dotter, gelegt von Vögeln und Reptilien."], "primary"
    )
    bird = _source(
        "Vogel",
        [
            "Ein Vogel fliegt bei Tag über das Land und singt dabei sein Lied, meist in einem Baum.",
            "Das Weibchen legt zwei Eier in das Nest und brütet sie zwei Wochen lang aus.",
        ],
    )

    chunks, _, _ = segment_corpus([primary, bird], HeadingLexicon.empty(), 100)

    assert [chunk.text for chunk in chunks if chunk.source_id == bird.source_id] == [
        bird.sections[0].paragraphs[1].text
    ]


def test_the_subtopics_of_a_short_topic_name_it_as_a_word() -> None:
    primary = _source(
        "Ei", ["Ein Ei ist eine Keimzelle mit Schale und Dotter, gelegt von Vögeln und Reptilien."], "primary"
    )
    neighbours = [
        _source(title, ["Ein Absatz über etwas anderes, lang genug für einen Baustein."])
        for title in ("Reis", "Weißstorch", "Eier (Lebensmittel)")
    ]

    assert subtopics([primary, *neighbours], primary) == ["Eier (Lebensmittel)"]


def test_a_corpus_names_its_main_article_in_one_way() -> None:
    """WA-05 (audit 2026-09-28): four places picked the main article, two of them the first source when none was
    marked and two nothing; then the topic stem was missing, and linked articles went into the corpus unfiltered."""
    first = _source("Ei", ["Ein Ei ist eine Keimzelle mit Schale und Dotter, gelegt von Vögeln und Reptilien."])
    bird = _source(
        "Vogel",
        [
            "Ein Vogel fliegt bei Tag über das Land und singt dabei sein Lied, meist in einem Baum.",
            "Das Weibchen legt zwei Eier in das Nest und brütet sie zwei Wochen lang aus.",
        ],
    )
    main = _source("Ei", ["Ein Ei ist eine Keimzelle."], "primary")

    chunks, _, _ = segment_corpus([first, bird], HeadingLexicon.empty(), 100)

    assert (primary_of([bird, main]), primary_of([first, bird]), primary_of([])) == (main, first, None)
    assert [chunk.text for chunk in chunks if chunk.source_id == bird.source_id] == [
        bird.sections[0].paragraphs[1].text
    ]
