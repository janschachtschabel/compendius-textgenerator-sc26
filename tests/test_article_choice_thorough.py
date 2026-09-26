"""article_choice=llm-thorough (D61): the LLM also checks a sure resolution of a word with several meanings.

Point 5 of the decision paper, measured as M35 on the 94 gold queries of eval/artikelwahl: article_choice=llm shows
the model only what the rules are unsure about, so a word the rules resolve surely and wrongly stays wrong. Checking
the sure resolutions of ambiguous words too - a meaning taken from a disambiguation page, or an exact title that has
a "(Begriffsklärung)" page - got 93 instead of 91 right and spoiled none of the 44 right ones it checked, at 64
instead of 18 questions. Jan, 2026-09-26: "mehrdeutige Wörter prüfen"; as proposed with M35, the best-quality
profiles check them and balanced keeps asking only where the rules are unsure.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from libzim.writer import Creator

from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.sources.zim.registry import ZimRegistry
from tests.conftest import HtmlItem
from tests.test_article_choice import by_prompt
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

LIST = "<ul>{items}</ul><p>Dies ist eine Begriffsklärungsseite zur Unterscheidung mehrerer Begriffe.</p>"
ARTICLES = {
    "Strom": "<p>Ein Strom ist ein großes Fließgewässer, das ins Meer mündet.</p>",
    "Strom (Begriffsklärung)": LIST.format(
        items='<li><a href="Strom" title="Strom">Strom</a>, Fließgewässer</li>'
        '<li><a href="Elektrischer_Strom" title="Elektrischer Strom">Elektrischer Strom</a>, Physik</li>'
    ),
    "Elektrischer Strom": "<p>Elektrischer Strom ist die gerichtete Bewegung von Ladungsträgern.</p>",
    "Baum": "<p>Ein Baum ist eine verholzte Pflanze mit Stamm, Ästen und Krone.</p>",
    "Baum (Begriffsklärung)": LIST.format(
        items='<li><a href="Baum" title="Baum">Baum</a>, Pflanze</li>'
        '<li><a href="Baum_(Datenstruktur)" title="Baum (Datenstruktur)">Baum (Datenstruktur)</a>, Struktur</li>'
    ),
    "Baum (Datenstruktur)": "<p>Ein Baum verbindet Knoten ohne Kreise.</p>",
}

Candidates = Sequence[tuple[str, str]]


@pytest.fixture(scope="module")
def ambiguous(tmp_path_factory: pytest.TempPathFactory) -> ZimRegistry:
    path = tmp_path_factory.mktemp("zim") / "wikipedia_de_mehrdeutig_2026-01.zim"
    with Creator(str(path)) as creator:
        creator.set_mainpath("Strom")
        for title, body in ARTICLES.items():
            html = f"<html><head><title>{title}</title></head><body>{body}</body></html>"
            creator.add_item(HtmlItem(title.replace(" ", "_"), title, html))
    return ZimRegistry([path])


class Recording:
    """A chooser that notes the titles it was offered and picks the place it was told to."""

    def __init__(self, pick: int) -> None:
        self.pick = pick
        self.offered: list[list[str]] = []

    def __call__(self, candidates: Candidates) -> tuple[int | None, str | None]:
        self.offered.append([title for title, _ in candidates])
        return self.pick, None


def refuse(candidates: Candidates) -> tuple[int | None, str | None]:
    raise AssertionError("the chooser was asked")


def test_a_sure_exact_title_with_a_disambiguation_page_is_checked(ambiguous: ZimRegistry) -> None:
    chooser = Recording(pick=1)
    resolution = ambiguous.resolve_topic("Strom", chooser=chooser, thorough=True)
    assert chooser.offered == [["Strom", "Elektrischer Strom"]], "the rules' article first, then the meanings"
    assert resolution.title == "Elektrischer Strom" and resolution.method == "llm" and not resolution.confident
    assert resolution.alternatives[0] == "Strom", "the rules' article stays visible"


def test_without_thorough_the_sure_title_is_not_shown(ambiguous: ZimRegistry) -> None:
    resolution = ambiguous.resolve_topic("Strom", chooser=refuse)
    assert resolution.title == "Strom" and resolution.method == "title" and resolution.confident


def test_a_meaning_the_rules_took_surely_from_a_disambiguation_page_is_checked(ambiguous: ZimRegistry) -> None:
    assert ambiguous.resolve_topic("Baum", terms=["informatik", "daten"]).confident  # the rules alone are sure
    chooser = Recording(pick=0)
    resolution = ambiguous.resolve_topic("Baum", terms=["informatik", "daten"], chooser=chooser, thorough=True)
    assert chooser.offered == [["Baum", "Baum (Datenstruktur)"]], "the meanings in the order of their page"
    assert resolution.title == "Baum" and resolution.method == "llm"


def test_a_title_without_meanings_is_not_checked_even_thoroughly(ambiguous: ZimRegistry) -> None:
    resolution = ambiguous.resolve_topic("Elektrischer Strom", chooser=refuse, thorough=True)
    assert resolution.title == "Elektrischer Strom" and resolution.method == "title" and resolution.confident


@pytest.mark.parametrize(("preset", "asked"), [("balanced", False), ("best-quality", True)])
def test_the_best_quality_profiles_check_a_sure_word_with_meanings(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch, preset: str, asked: bool
) -> None:
    # "Optik" is an exact title of the test archive, and "Optik (Begriffsklärung)" lists it among its meanings
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(by_prompt({"wahl": 1})), per_request=100_000))
    request = GenerateRequest(topic="Optik", parts=["world"], preset=preset, matcher="hybrid_light")  # type: ignore[arg-type]
    result = service.generate(request)

    choice = result.audit.llm["article_choice"] if result.audit.llm else {}
    assert choice["requested"] == ("llm-thorough" if asked else "llm")
    assert choice["asked"] is asked and result.resolution.title == "Optik"
    assert result.resolution.method == ("llm" if asked else "title")
