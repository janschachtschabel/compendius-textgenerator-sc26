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


def test_parts_without_world_say_nothing_about_generating_part_one(service: CompendiumService) -> None:
    # Mode and matcher concern part 1: a hybrid request for part 2 alone is no fallback to the rule-based mode,
    # and counting it as one would keep KompendiumHybridFallbacks firing
    result = service.generate(GenerateRequest(topic="Optik", parts=["curricula"], mode="hybrid-quality"))
    assert result.mode == "rule-based"
    assert {"mode_requested", "llm", "matcher"}.isdisjoint(result.frontmatter)
    assert result.audit.llm is None and result.audit.matcher is None


def test_part_two_alone_counts_no_paragraphs_of_a_part_one(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik", parts=["curricula"]))
    # Segmentation and chunk cap serve part 1; their counts (and the truncation metric) would describe a part 1
    # that was never written
    assert result.audit.chunks_total == 0 and result.audit.chunks_truncated == 0
    assert "segment" not in result.audit.timings_ms
    assert result.curricula is not None and "Geometrische Optik" in result.curricula.keywords  # still from the corpus


def test_a_corrupt_cache_file_is_reported_as_unreadable_not_as_missing(
    sample_zims: dict[str, Path], registry: ZimRegistry, tmp_path: Path
) -> None:
    settings = make_settings(sample_zims.values(), tmp_path / "state")
    settings.state_dir.mkdir(parents=True)
    settings.lehrplan_db_path.write_bytes(b"not a database at all")
    service = build_service(settings, registry, TemplateManager())
    result = service.generate(GenerateRequest(topic="Optik", parts=["curricula"]))
    # Operators should repair the file, not look for a missing one
    assert result.curricula is not None and result.curricula.summary == {"reason": "cache_unreadable"}
    assert "nicht lesbar" in result.curricula.markdown and "nicht vorhanden" not in result.curricula.markdown


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
    assert "nicht lesbar" in result.curricula.markdown
