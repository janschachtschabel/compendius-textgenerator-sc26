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
    finding = topic_scope_finding(asked, article, normalized=asked, covers=covers, method=method, about_topic=False)

    assert finding is not None and finding.rule == TOPIC_SCOPE and finding.section_id is None
    assert finding.severity == "info"
    assert article in finding.message and asked in finding.message
    assert "best-quality-generated" in finding.message and "best-coverage-generated" in finding.message


@pytest.mark.parametrize(
    ("asked", "article", "covers", "method", "about_topic"),
    [
        ("Optik", "Optik", None, "title", False),  # the archive has an article of that very name
        ("Lichtlehre", "Optik", None, "title", False),  # a redirect: the same topic for the archive
        ("Optik", "Optik", False, "title", False),  # an article of that very name, whatever N says
        ("Lichtlehre", "Optik", True, "llm", False),  # N: the overview covers the topic as asked
        ("Edelgase", "Edelgas", None, "variant", False),  # an inflected form is the same topic
        ("Linse", "Linse (Optik)", None, "disambiguation", False),  # a meaning of the word
        ("Art", "Art (Biologie)", None, "disambiguation", False),  # a short word is the same word
        ("Kreislauf des Wassers", "Wasserkreislauf", None, "variant", False),  # the words of a compound
        ("Optik in Klasse 7", "Optik", None, "title", False),  # a level is no aspect: the topic without it decides
        ("OER-Förderungen", "Open Educational Resources", False, "llm", True),  # the LLM wrote about the topic as asked
        ("OER-Förderungen", None, None, None, False),  # no article, nothing to compare
    ],
)
def test_a_topic_its_article_covers_or_a_text_written_about_the_topic_gets_no_hint(
    asked: str, article: str | None, covers: bool | None, method: str | None, about_topic: bool
) -> None:
    normalized = "Optik" if asked == "Optik in Klasse 7" else asked
    finding = topic_scope_finding(
        asked, article, normalized=normalized, covers=covers, method=method, about_topic=about_topic
    )
    assert finding is None
