"""The rules of the topic resolution through resolve_topic, and an archive without a full-text index (audit
2026-09-28, TE-14).

The helpers of the rules had tests of their own, their interplay in _resolve_by_rules had none: the inflected form,
the compound of a genitive phrase and the work that carries the article of a topic never ran. Both sample archives
have a full-text index, so the way without one never ran either, nor the fallbacks for a libzim that fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from libzim.writer import Creator

from app.knowledge.corpus_sources import build_corpus
from app.knowledge.resolution import resolve_topic
from app.sources.zim import archive as archive_module
from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import ZimRegistry
from app.templates.manager import TemplateManager
from tests.conftest import HtmlItem

GLASS = (
    "Ein Brillenglas ist die Linse einer Brille. Es wird aus Glas oder Kunststoff geschliffen, gehärtet, entspiegelt "
    "und in die Fassung eingesetzt. Seine Stärke wird in Dioptrien angegeben; ein Glas für Kurzsichtige ist in der "
    "Mitte dünner als am Rand, eines für Weitsichtige dicker. Gleitsichtgläser verbinden mehrere Stärken in einem "
    "Glas, sodass die Nähe durch den unteren Teil und die Ferne durch den oberen Teil gesehen wird."
)


def _page(title: str, body: str) -> str:
    return f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>"


@pytest.fixture(scope="module")
def without_fulltext(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A Wikipedia archive of three articles and no full-text index: the topic, a film of its name, a sub-article."""
    out = tmp_path_factory.mktemp("zim") / "wikipedia_de_ohne-volltext_2026-01.zim"
    with Creator(str(out)).config_indexing(False, "deu") as creator:
        creator.set_mainpath("Brille")
        for key, value in {"Name": "wikipedia_de_ohne-volltext", "Title": "Wikipedia", "Creator": "Wikipedia"}.items():
            creator.add_metadata(key, value)
        creator.add_item(
            HtmlItem(
                "Brille",
                "Brille",
                _page(
                    "Brille",
                    "<p>Eine Brille ist ein Gestell mit zwei Gläsern vor den Augen, das die Sicht verbessert; mehr "
                    "unter <a href='Brillenglas'>Brillenglas</a>.</p><h2>Geschichte</h2><p>Die ersten Brillen "
                    "entstanden im 13. Jahrhundert in Italien, als geschliffene Lesesteine gefasst wurden.</p>",
                ),
            )
        )
        creator.add_item(
            HtmlItem(
                "Die_Brille",
                "Die Brille",
                _page("Die Brille", "<p>Die Brille ist ein deutscher Spielfilm aus dem Jahr 1985 von Hans Muster.</p>"),
            )
        )
        creator.add_item(HtmlItem("Brillenglas", "Brillenglas", _page("Brillenglas", f"<p>{GLASS}</p>")))
    return out


def test_an_inflected_topic_resolves_to_its_base_title(registry: ZimRegistry) -> None:
    resolution = resolve_topic(registry, "Linsen")

    assert (resolution.title, resolution.method, resolution.confident) == ("Linse", "variant", True)


def test_a_genitive_phrase_resolves_to_its_compound(registry: ZimRegistry) -> None:
    resolution = resolve_topic(registry, "Mikroskop des Lichts")

    assert (resolution.title, resolution.method, resolution.confident) == ("Lichtmikroskop", "variant", False)


def test_a_work_that_carries_the_article_of_the_topic_gives_way_to_the_topic(without_fulltext: Path) -> None:
    resolution = resolve_topic(ZimRegistry([without_fulltext]), "Die Brille")

    assert (resolution.title, resolution.method, resolution.confident) == ("Brille", "title", True)
    assert resolution.alternatives[0] == "Die Brille"  # the film stays on offer


def test_an_archive_without_a_full_text_index_resolves_and_builds_by_titles(without_fulltext: Path) -> None:
    registry = ZimRegistry([without_fulltext])
    assert not ZimArchive(without_fulltext).has_fulltext and ZimArchive(without_fulltext).search("Brille") == []

    guessed = resolve_topic(registry, "Brillenglä")  # no title, no variant, no hits: the title suggestions decide
    corpus = build_corpus(registry, resolve_topic(registry, "Brille"), TemplateManager().get("sc26").slots, 10)

    assert (guessed.title, guessed.method, guessed.confident) == ("Brillenglas", "suggestion", False)
    assert [(source.title, source.origin) for source in corpus] == [("Brille", "primary"), ("Brillenglas", "linked")]


def test_a_failing_libzim_is_no_answer_rather_than_an_error(
    sample_zims: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = ZimArchive(sample_zims["wikipedia"])

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("libzim")

    class TitlesFail:
        """The archive, but its title lookup raises, as libzim does on odd input."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def has_entry_by_title(self, title: str) -> bool:
            raise RuntimeError("libzim")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    monkeypatch.setattr(archive_module, "SuggestionSearcher", fail)
    monkeypatch.setattr(archive_module, "Searcher", fail)
    monkeypatch.setattr(archive, "_archive", TitlesFail(archive._archive))

    assert archive.suggest("Opt") == [] and archive.search("Optik") == []
    found = archive.read("Optik")  # the path lookup after the failed title lookup
    assert found is not None and found.title == "Optik"
