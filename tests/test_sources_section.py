"""Sources block of part 1: the licence note without sources names no empty list."""

from app.synthesis.sources_section import build_sources_section


def test_the_licence_note_without_sources_names_no_empty_list() -> None:
    text = build_sources_section([], [], facets_visible=False)
    assert "()" not in text and "Lizenz- und Attributionshinweis" in text
