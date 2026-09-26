"""Part 2 inside a generated compendium: keywords from part 1, cache present or missing, parts selection."""

import json
from pathlib import Path

import pytest

from app.domain.requests import GenerateRequest
from app.main import build_service
from app.service import CompendiumService, LlmNotConfiguredError
from app.settings import Settings
from app.sources.zim.registry import ZimRegistry
from app.templates.manager import TemplateManager
from tests.conftest import make_settings
from tests.test_lehrplan_api import write_broken_cache, write_cache
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway


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
    # "Lichtbrechung an Linsen" names Optik only in its heading "Lernbereich 2: Optik": counted with its area (B, D58),
    # and the JSON answer still lists it with where it was found
    assert "- *1 Element dieses Bereichs; das Thema steht nur in der Überschrift*" in markdown
    assert "„Lichtbrechung an Linsen“" not in markdown and result.curricula.summary["bundled"] == 1
    assert [(entry["label"], entry["matched_in"]) for entry in result.curricula.entries] == [
        ("Lichtbrechung an Linsen", "parent")
    ]
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
    # The LLM switches and the matcher concern part 1: an LLM request for part 2 alone is no fallback to the
    # rule-based path, and counting it as one would keep KompendiumLlmFallbacks firing
    request = GenerateRequest(topic="Optik", parts=["curricula"], extraction="llm", generation="llm")
    result = service.generate(request)
    assert result.generation == "rule-based"
    assert result.extraction == "rule-based"
    assert {"generation_requested", "extraction_requested", "llm", "matcher"}.isdisjoint(result.frontmatter)
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


CHECKED = {"topic": "Optik", "parts": ["world", "curricula"], "subject": "Physik", "preset": "llm-free"}


def test_curriculum_check_llm_without_a_configured_llm_is_refused(
    service: CompendiumService, settings: Settings
) -> None:
    """D53, D58: what needs an LLM is refused on a server without one instead of quietly running the rules."""
    write_cache(settings.state_dir)
    with pytest.raises(LlmNotConfiguredError, match="curriculum_check=llm"):
        service.generate(GenerateRequest(**CHECKED, curriculum_check="llm"))


def test_the_llm_check_drops_what_does_not_fit_and_says_so(
    service: CompendiumService, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_cache(settings.state_dir)
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(lambda body: json.dumps({"e1": 0}))))
    result = service.generate(GenerateRequest(**CHECKED, curriculum_check="llm"))
    assert result.curricula is not None and result.curricula.entries == []
    assert result.curricula.summary["matches"] == 0
    assert result.curricula.summary["llm_check"] == {"rated": 1, "answered": 1, "dropped": 1, "fallbacks": {}}
    audit = result.audit.llm
    assert audit is not None and audit["curriculum_check"]["used"] == "llm"
    assert audit["curriculum_check"]["dropped"] == 1
    assert result.audit.llm_tokens is not None and result.audit.llm_tokens["calls"] == 1
    assert "curriculum_check@v1" in result.frontmatter["llm"]["prompts"]


def test_a_heading_only_element_the_llm_rates_fitting_is_listed_on_its_own(
    service: CompendiumService, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_cache(settings.state_dir)
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(lambda body: json.dumps({"e1": 2}))))
    result = service.generate(GenerateRequest(**CHECKED, curriculum_check="llm"))
    assert result.curricula is not None
    assert "„Lichtbrechung an Linsen“ (Kompetenz)" in result.markdown
    assert "das Thema steht nur in der Überschrift" not in result.markdown
    assert [entry["note"] for entry in result.curricula.entries] == [2]


def test_the_best_quality_profiles_check_from_a_budget_of_their_own(
    service: CompendiumService, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D59: next to matcher llm the 60,000 tokens of a request cover about 400 elements (M32); best-quality and
    best-quality-generated spend from LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY. With the other cap far too small,
    only they still check."""
    write_cache(settings.state_dir)
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(lambda body: json.dumps({"e1": 2})), per_request=100))
    asked = {"topic": "Optik", "parts": ["curricula"], "subject": "Physik"}
    best = service.generate(GenerateRequest(**asked, preset="best-quality")).audit.llm
    tight = service.generate(GenerateRequest(**asked, preset="balanced", curriculum_check="llm")).audit.llm
    assert best is not None and best["curriculum_check"]["answered"] == 1
    assert tight is not None and tight["curriculum_check"]["answered"] == 0
    assert any("Token-Budget der Anfrage" in reason for reason in tight["curriculum_check"]["fallbacks"])


def test_while_the_b_api_is_away_the_rules_decide_part_two_and_the_audit_says_why(
    service: CompendiumService, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_cache(settings.state_dir)
    fake = FakeBApi(lambda body: json.dumps({"e1": 0}))
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    monkeypatch.setattr(service, "llm_unavailable", lambda: "b-api gerade nicht erreichbar (Test)")
    result = service.generate(GenerateRequest(**CHECKED, curriculum_check="llm"))
    assert result.curricula is not None and result.curricula.summary["bundled"] == 1 and fake.bodies == []
    audit = result.audit.llm
    assert audit is not None and audit["curriculum_check"]["used"] == "rule-based"
    assert audit["curriculum_check"]["fallback"] == "b-api gerade nicht erreichbar (Test)"
