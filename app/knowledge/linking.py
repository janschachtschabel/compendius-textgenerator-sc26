"""The article a mention names (docs/umbau.md U3), shared by /entities and the article of a material (D47)."""

from __future__ import annotations

from collections.abc import Sequence

from app.knowledge.recognise import Mention, title_candidates
from app.sources.zim.archive import ZimArchive, ZimArticle


def article_of(archives: Sequence[ZimArchive], mention: Mention) -> tuple[ZimArchive, ZimArticle] | None:
    """The article of this name, from the first archive that has it; a disambiguation page is none.

    A mention of the dictionary names its title already; a name of the model may stand in the genitive
    ("Abraham Lincolns"), so its base form is tried after the text.
    """
    titles = [mention.title] if mention.title else title_candidates(mention.text)
    for archive in archives:
        article = next((found for title in titles if (found := archive.read(title)) is not None), None)
        if article is None or archive.parse(article).is_disambiguation:
            continue
        return archive, article
    return None
