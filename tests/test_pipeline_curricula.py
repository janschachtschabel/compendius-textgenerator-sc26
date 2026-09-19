"""Part 2 inside a generated compendium: keywords from part 1, cache present or missing, parts selection."""

from pathlib import Path

from app.domain.requests import GenerateRequest
from app.main import build_service
from app.service import CompendiumService
from app.settings import Settings
from app.sources.zim.registry import ZimRegistry
from app.templates.manager import TemplateManager
from tests.conftest import make_settings
from tests.test_lehrplan_api import write_broken_cache, write_cache


def test_generate_appends_part_two_from_the_cache(service: CompendiumService, settings: Settings) -> None:
    write_cache(settings.state_dir)
    result = service.generate(GenerateRequest(topic="Optik", parts=["world", "curricula"], subject="Physik"))
    assert result.curricula is not None
    assert result.curricula.summary["matches"] == 1
    assert result.curricula.keywords[0] == "Optik"
    assert result.frontmatter["parts"] == ["world", "curricula"]
    markdown = result.markdown
    assert markdown.index("## Teil 1 · Weltwissen") < markdown.index("## Teil 2 · Lehrplanbezüge")
    assert "<!-- f: Bundesland=Sachsen; Bildungsstufe=Sek I; Klassenstufe=7; Schulart=Gymnasium;" in markdown
    assert "„Lichtbrechung an Linsen“ (Kompetenz)" in markdown
    assert result.audit.timings_ms["curricula"] >= 0


def test_world_only_leaves_part_two_out(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"]))
    assert result.curricula is None
    assert "Teil 2" not in result.markdown
    assert result.frontmatter["parts"] == ["world"]


def test_missing_cache_yields_the_hint_instead_of_an_error(
    sample_zims: dict[str, Path], registry: ZimRegistry, tmp_path: Path
) -> None:
    settings = make_settings(sample_zims.values(), tmp_path / "state-empty")
    service = build_service(settings, registry, TemplateManager(custom_dir=settings.state_dir / "templates"))
    result = service.generate(GenerateRequest(topic="Optik"))
    assert result.curricula is not None and result.curricula.available is False
    assert "Lehrplan-Cache" in result.markdown


def test_parts_without_world_skip_part_one(service: CompendiumService, settings: Settings) -> None:
    write_cache(settings.state_dir)
    result = service.generate(GenerateRequest(topic="Optik", parts=["curricula"], subject="Physik"))
    assert result.frontmatter["parts"] == ["curricula"]
    assert result.sections == [] and result.sources == []
    assert "Teil 1" not in result.markdown and "## Teil 2 · Lehrplanbezüge" in result.markdown
    assert result.curricula is not None and result.curricula.summary["matches"] == 1
    assert result.audit.chunks_assigned == 0 and result.audit.citations == 0
    assert "match" not in result.audit.timings_ms and "synthesize" not in result.audit.timings_ms


def test_the_chunk_cap_does_not_cost_part_two_its_subtopics(
    sample_zims: dict[str, Path], registry: ZimRegistry, tmp_path: Path
) -> None:
    # CORPUS_MAX_CHUNKS decides which paragraphs part 1 uses; part 2 searches for the sub-topics of the whole corpus.
    keywords: dict[int, list[str]] = {}
    for cap in (5000, 20):
        settings = make_settings(sample_zims.values(), tmp_path / f"state-{cap}", corpus_max_chunks=cap)
        service = build_service(settings, registry, TemplateManager())
        result = service.generate(GenerateRequest(topic="Optik", parts=["world", "curricula"]))
        assert result.curricula is not None
        keywords[cap] = result.curricula.keywords
    assert result.audit.chunks_truncated > 0  # the cap of 20 bites
    assert "Geometrische Optik" in keywords[5000]
    assert keywords[20] == keywords[5000]


def test_unreadable_cache_yields_the_hint_instead_of_an_error(
    sample_zims: dict[str, Path], registry: ZimRegistry, tmp_path: Path
) -> None:
    settings = make_settings(sample_zims.values(), tmp_path / "state-broken")
    write_broken_cache(settings.state_dir)
    service = build_service(settings, registry, TemplateManager(custom_dir=settings.state_dir / "templates"))
    result = service.generate(GenerateRequest(topic="Optik", parts=["world", "curricula"]))
    assert result.curricula is not None and result.curricula.available is False
    assert result.curricula.summary["reason"] == "cache_unreadable"
    assert "## Teil 2 · Lehrplanbezüge" in result.markdown and len(result.sections) > 0
