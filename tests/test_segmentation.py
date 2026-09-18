from pathlib import Path

from app.domain.models import ArticleSection, Paragraph, Source, SourceRole
from app.knowledge.segmentation import segment_source, split_sentences
from app.matching.lexicon import HeadingLexicon
from app.sources.zim.html import parse_article
from tests.conftest import ROOT


def _lexicon() -> HeadingLexicon:
    return HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml")


def _source(html: str, title: str, *, primary: bool = True) -> Source:
    parsed = parse_article(html, title)
    return Source(
        source_id=f"wikipedia:{title}",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title=title,
        url=f"https://de.wikipedia.org/wiki/{title}",
        is_primary=primary,
        links=parsed.links,
        aliases=parsed.aliases,
        sections=parsed.sections,
    )


def test_ordinal_numbers_do_not_split_sentences() -> None:
    sentences = split_sentences("Die Visby-Linsen stammen aus dem 11. Jahrhundert. Sie sind erstaunlich gut.")
    assert sentences == ["Die Visby-Linsen stammen aus dem 11. Jahrhundert.", "Sie sind erstaunlich gut."]


def test_abbreviations_and_dates_are_protected() -> None:
    sentences = split_sentences("Linsen bestehen z. B. aus Glas. Am 3. Oktober 1990 änderte sich vieles. Fertig.")
    assert len(sentences) == 3
    assert sentences[0] == "Linsen bestehen z. B. aus Glas."
    assert sentences[1].startswith("Am 3. Oktober 1990")


def test_initials_in_names_do_not_end_a_sentence() -> None:
    """Measured 2026-09-18: "John D. Hamaker …" was cut after the initial and the head was dropped as uncited."""
    text = (
        "John D. Hamaker warnte vor einer Eiszeit. Die Forschung widersprach ihm. "
        "Pflanzen brauchen Vitamin C. Die Zufuhr schwankt. J. S. Bach prägte die Epoche."
    )
    assert split_sentences(text) == [
        "John D. Hamaker warnte vor einer Eiszeit.",
        "Die Forschung widersprach ihm.",
        "Pflanzen brauchen Vitamin C.",
        "Die Zufuhr schwankt.",
        "J. S. Bach prägte die Epoche.",
    ]


def test_segmentation_of_optik(optik_html: str) -> None:
    source = _source(optik_html, "Optik")
    chunks = segment_source(source, _lexicon())
    assert chunks, "expected chunks"
    lead = chunks[0]
    assert lead.is_lead and lead.text.startswith("Die Optik")
    headings = {c.heading for c in chunks}
    assert not headings & {"Einzelnachweise", "Weblinks", "Literatur", "Siehe auch"}
    assert source.reference_lines, "Literatur/Weblinks should feed the reference lines"
    by_heading = {c.heading: c for c in chunks}
    assert by_heading["Geschichte der Sehhilfen"].lexicon_slot == "entwicklung_ausblick"
    assert by_heading["Bekannte Optiker"].lexicon_slot == "akteure"
    teil = next(c for c in chunks if c.heading_path and c.heading_path[0] == "Teilbereiche der Optik")
    assert teil.lexicon_slot == "systematik"
    assert all(c.chunk_id.startswith("wikipedia:Optik:c") for c in chunks)


def test_section_leads_are_marked(optik_html: str) -> None:
    chunks = segment_source(_source(optik_html, "Optik"), _lexicon())
    h2_first = [c for c in chunks if c.heading_level == 2 and c.is_section_lead]
    assert h2_first, "first paragraph under an h2 must be a section lead"


def test_intro_and_following_list_are_merged() -> None:
    from app.domain.models import ChunkKind, Paragraph
    from app.knowledge.segmentation import _merge_intro_lists

    paragraphs = [
        Paragraph(text="Das Arbeitsfeld eines Optotechnikers umfasst"),
        Paragraph(kind=ChunkKind.LIST, text="- Lichtdesign\n- Medizintechnik"),
        Paragraph(text="Ein normaler Satz folgt und bleibt eigenständig."),
    ]
    merged = _merge_intro_lists(paragraphs)
    assert len(merged) == 2
    assert merged[0].kind is ChunkKind.TEXT
    assert "umfasst Lichtdesign; Medizintechnik." in merged[0].text


def test_klexikon_boilerplate_is_dropped() -> None:
    html = (Path(__file__).parent / "fixtures" / "zim_html" / "klexikon" / "Licht.html").read_text(encoding="utf-8")
    chunks = segment_source(_source(html, "Licht", primary=False), _lexicon())
    assert not any("spenden" in c.text.lower() for c in chunks)


def test_pointer_lines_are_dropped() -> None:
    body = "Ein richtiger Absatz mit genug Inhalt, um als Chunk zu gelten und Text zu liefern."
    source = Source(
        source_id="wikipedia:X",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title="X",
        url="u",
        is_primary=True,
        sections=[
            ArticleSection(
                heading="Teil",
                path=["Teil"],
                level=2,
                paragraphs=[
                    Paragraph(text="→ Hauptartikel: Kohärenz und Interferenz sowie Beugung am Spalt"),
                    Paragraph(text="Siehe auch: Liste großer historischer Vulkanausbrüche und Erdbeben"),
                    Paragraph(text=body),
                ],
            )
        ],
    )
    assert [c.text for c in segment_source(source, _lexicon())] == [body]


def _plain_source(*texts: str) -> Source:
    return Source(
        source_id="wikipedia:Y",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title="Y",
        url="u",
        is_primary=True,
        sections=[
            ArticleSection(heading="Teil", path=["Teil"], level=2, paragraphs=[Paragraph(text=t) for t in texts])
        ],
    )


def test_formula_intros_captions_and_figure_references_are_dropped() -> None:
    body = "Ein vollständiger Absatz mit Aussagegehalt, der als Fließtext in das Kompendium übernommen werden kann."
    source = _plain_source(
        "Die molare freie Standardbildungsenthalpie für ATP aus ADP und Phosphat beträgt:",
        "vereinfachte Netto-Reaktionsgleichung für die oxygene Photosynthese",
        "In Figur 4 hat die gesamte braune Fläche einen Anteil von an der Gesamtfläche und die hellbraune Fläche.",
        body,
    )
    assert [c.text for c in segment_source(source, _lexicon())] == [body]
