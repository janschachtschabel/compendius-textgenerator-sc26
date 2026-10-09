"""The twin of a topic in a further archive: the article of the main article's own title (D100, M85).

Taken over an alias, the twin was often another meaning: Klexikon's general *Strom*, which starts with rivers, for
"Elektrischer Strom", and *Zelle*, which starts with prison cells, for "Zelle (Biologie)"; its first paragraph went to
the topic definition. M85 measured the exact title alone: on the 59 gold requests the off-topic Klexikon paragraphs
fell from 12 to 2 for 4 fitting twins, on 35 held-out requests from 10 to 2 for none. A redirect of the title in the
further archive still counts.
"""

from __future__ import annotations

from pathlib import Path

from libzim.writer import Creator, Hint

from app.domain.models import Resolution
from app.knowledge.corpus_sources import build_corpus
from app.sources.zim.registry import ZimRegistry
from tests.conftest import HtmlItem

TITLE = "Elektrischer Strom"
LEAD = "<p>Der <b>elektrische Strom</b> oder kurz <b>Strom</b> ist die gerichtete Bewegung von Ladungsträgern.</p>"


def zim(path: Path, pages: dict[str, str], redirects: tuple[tuple[str, str], ...] = ()) -> Path:
    with Creator(str(path)) as creator:
        creator.set_mainpath(next(iter(pages)).replace(" ", "_"))
        for title, body in pages.items():
            html = f"<html><head><title>{title}</title></head><body>{body}</body></html>"
            creator.add_item(HtmlItem(title.replace(" ", "_"), title, html))
        for title, target in redirects:
            creator.add_redirection(
                title.replace(" ", "_"), title, target.replace(" ", "_"), {Hint.FRONT_ARTICLE: True}
            )
    return path


def twins(tmp_path: Path, klexikon: dict[str, str], redirects: tuple[tuple[str, str], ...] = ()) -> list[str]:
    """The twins the corpus of "Elektrischer Strom" takes from a Klexikon with ``klexikon``'s pages."""
    wikipedia = zim(tmp_path / "wikipedia_de_twin_2026-01.zim", {TITLE: LEAD})
    kids = zim(tmp_path / "klexikon_de_twin_2026-08.zim", klexikon, redirects)
    resolution = Resolution(
        query=TITLE, normalized=TITLE, title=TITLE, path=TITLE.replace(" ", "_"), project="wikipedia"
    )
    sources = build_corpus(ZimRegistry([wikipedia, kids]), resolution, [], 12)
    return [f"{source.project}:{source.title}" for source in sources if source.origin == "same_topic"]


def test_an_alias_of_the_main_article_brings_no_twin(tmp_path: Path) -> None:
    rivers = "<p>Ein <b>Strom</b> ist ein großer Fluss, der direkt ins Meer fließt.</p>"
    assert twins(tmp_path, {"Strom": rivers}) == []


def test_the_main_articles_own_title_brings_its_twin(tmp_path: Path) -> None:
    current = "<p>Elektrischer Strom fließt durch Kabel und bringt Lampen zum Leuchten.</p>"
    assert twins(tmp_path, {TITLE: current}) == [f"klexikon:{TITLE}"]


def test_a_redirect_of_the_own_title_still_brings_its_twin(tmp_path: Path) -> None:
    energy = "<p>Elektrizität ist eine Form von Energie, die durch Kabel fließt.</p>"
    assert twins(tmp_path, {"Elektrizität": energy}, ((TITLE, "Elektrizität"),)) == ["klexikon:Elektrizität"]
