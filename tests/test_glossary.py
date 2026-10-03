"""The glossary of a compendium: which side articles it names as narrower terms of the topic."""

from app.domain.models import ArticleSection, Paragraph, Source
from app.synthesis.glossary import build_glossary


def _source(title: str, *, primary: bool = False) -> Source:
    lead = ArticleSection(paragraphs=[Paragraph(text=f"{title} ist ein Werk, das in diesem Beispiel definiert wird.")])
    return Source(
        source_id=f"wikipedia:{title}",
        project="wikipedia",
        title=title,
        url=f"https://de.wikipedia.org/wiki/{title.replace(' ', '_')}",
        is_primary=primary,
        sections=[lead],
    )


def _relation(markdown: str, term: str) -> str:
    row = next(line for line in markdown.splitlines() if line.startswith(f"| **{term}** |"))
    return row.split(" | ")[2].strip("`")


def test_a_side_article_is_narrower_only_when_its_title_holds_the_stem_of_the_topic() -> None:
    """KO-11: the glossary took the first five letters of the topic as its stem, a leading article with them, so
    "Der Prozess" made "Der Pate" a narrower term; it now takes the topic stem the corpus checks use."""
    primary = _source("Der Prozess", primary=True)
    sources = [primary, _source("Der Pate"), _source("Der Prozess (1962)")]

    markdown = build_glossary("Der Prozess", primary, sources, [])

    assert _relation(markdown, "Der Pate") == "skos:related"
    assert _relation(markdown, "Der Prozess (1962)") == "skos:narrower"
