"""V3 (M49; 07, points 12e and 14): a compendium about another article than the topic as asked says which profiles
write about the topic.

Jan, 2026-10-02: a verbatim text keeps the article it prints as its heading (D12), and the check of the compendium
names the asked topic and the two writing profiles, which keep groups and aspects (M52: fit 4.2 to 5.0 against at
most 3.8). The question N says whether its overview covers the topic as asked (prompt topic_articles v2); without it
(llm-free) the words of the normalized topic decide.
"""

from __future__ import annotations

import pytest

from app.synthesis.lint import TOPIC_SCOPE, topic_scope_finding


@pytest.mark.parametrize(
    ("asked", "article", "covers", "method"),
    [
        ("OER-Förderungen", "Open Educational Resources", False, "llm"),  # N: the overview covers the topic in part
        ("Dichter aus dem Mittelalter", "Walther von der Vogelweide", False, "llm"),  # a member stood in
        ("Dichter aus dem Mittelalter", "Sangspruchdichtung", None, "search"),  # llm-free: words of the topic missing
        ("Künstliche Intelligenz im Unterricht", "Künstliche Intelligenz", None, "search"),
        ("Inklusion im Sportunterricht", "Inklusive Pädagogik", None, "llm"),
        ("Gewaltenteilung in Deutschland", "Gewaltenteilung", None, "search"),  # the search found the umbrella
    ],
)
def test_a_topic_wider_or_narrower_than_its_article_names_the_profiles_that_write_about_it(
    asked: str, article: str, covers: bool | None, method: str
) -> None:
    finding = topic_scope_finding(asked, article, normalized=asked, covers=covers, method=method, verbatim=None)

    assert finding is not None and finding.rule == TOPIC_SCOPE and finding.section_id is None
    assert finding.severity == "info"
    assert article in finding.message and asked in finding.message
    assert "best-quality-generated" in finding.message and "best-coverage-generated" in finding.message


@pytest.mark.parametrize(
    ("asked", "article", "covers", "method", "verbatim"),
    [
        ("Optik", "Optik", None, "title", None),  # the archive has an article of that very name
        ("Lichtlehre", "Optik", None, "title", None),  # a redirect: the same topic for the archive
        ("Optik", "Optik", False, "title", None),  # an article of that very name, whatever N says
        ("Lichtlehre", "Optik", True, "llm", None),  # N: the overview covers the topic as asked
        ("Edelgase", "Edelgas", None, "variant", None),  # an inflected form is the same topic
        ("Linse", "Linse (Optik)", None, "disambiguation", None),  # a meaning of the word
        ("Art", "Art (Biologie)", None, "disambiguation", None),  # a short word is the same word
        ("Kreislauf des Wassers", "Wasserkreislauf", None, "variant", None),  # the words of a compound
        ("Optik in Klasse 7", "Optik", None, "title", None),  # a level is no aspect: the topic without it decides
        ("Optik in Klasse 7", "Optik", False, "title", None),  # whatever N said of its overview (review 2026-10-02)
        ("OER-Förderungen", "Open Educational Resources", False, "llm", 0),  # the LLM wrote every block about it
        ("OER-Förderungen", None, None, None, None),  # no article, nothing to compare
    ],
)
def test_a_topic_its_article_covers_or_a_text_written_about_the_topic_gets_no_hint(
    asked: str, article: str | None, covers: bool | None, method: str | None, verbatim: int | None
) -> None:
    normalized = "Optik" if asked == "Optik in Klasse 7" else asked
    finding = topic_scope_finding(
        asked, article, normalized=normalized, covers=covers, method=method, verbatim=verbatim
    )
    assert finding is None


@pytest.mark.parametrize(("verbatim", "counted"), [(1, "Ein Baustein gibt"), (3, "3 Bausteine geben")])
def test_blocks_a_writing_profile_left_verbatim_say_which_article_they_print(verbatim: int, counted: str) -> None:
    """Audit 2026-10-02, A10: once the LLM wrote one block, the hint was gone, although the blocks whose writing fell
    back print the article's words under the topic as asked. They get a hint of their own; the profile already writes
    about the topic, so it names no profile."""
    finding = topic_scope_finding(
        "OER-Förderungen",
        "Open Educational Resources",
        normalized="OER-Förderungen",
        covers=False,
        method="llm",
        verbatim=verbatim,
    )

    assert finding is not None and finding.rule == TOPIC_SCOPE and finding.severity == "info"
    assert finding.message.startswith(f"{counted} den Artikel „Open Educational Resources“ wörtlich wieder")
    assert "„OER-Förderungen“" in finding.message and "best-coverage-generated" not in finding.message
    assert finding.message.endswith(
        "hat ihn nicht zum Thema geschrieben." if verbatim == 1 else "hat sie nicht zum Thema geschrieben."
    )
