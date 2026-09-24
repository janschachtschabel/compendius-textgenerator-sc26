"""The preset switch sets the switches of part 1 to one of the three levels of the decision paper (D40, D41).

docs/entwicklung/07-entscheidungsvorlage.md recommends three combinations: llm-free, the default since D40, balanced,
where the LLM chooses the articles, and best-quality, where it also assigns the paragraphs. ``preset`` names one of
them; a switch the request sets itself wins over the preset, and without a preset the settings decide as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from app.api.v2.knowledge import KnowledgeRequest
from app.cli import main
from app.domain.requests import PRESETS, GenerateRequest, Preset
from app.service import CompendiumService
from app.settings import Settings
from tests.test_article_choice import by_prompt
from tests.test_cli_generate import cli_env  # noqa: F401 - the fixture of the CLI tests
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

SWITCHES = ("article_choice", "matcher", "extraction", "generation", "enrichment")


def test_the_shipped_defaults_are_the_llm_free_level() -> None:
    shipped = Settings(_env_file=None)  # type: ignore[call-arg]
    assert shipped.llm_article_choice_default == "rule-based" and shipped.matcher_default == "hybrid_light"
    assert (shipped.llm_extraction_default, shipped.llm_generation_default) == ("rule-based", "rule-based")
    assert shipped.llm_enrichment_default == "sources-only"


def test_the_presets_are_the_values_of_the_field() -> None:
    assert list(PRESETS) == list(get_args(Preset))
    assert all(set(values) == set(SWITCHES) for values in PRESETS.values())


@pytest.mark.parametrize(
    ("preset", "article_choice", "matcher"),
    [("llm-free", "rule-based", "hybrid_light"), ("balanced", "llm", "hybrid_light"), ("best-quality", "llm", "llm")],
)
def test_a_preset_sets_every_switch_of_part_1(preset: str, article_choice: str, matcher: str) -> None:
    request = GenerateRequest(topic="Optik", preset=preset)  # type: ignore[arg-type]
    assert (request.article_choice, request.matcher) == (article_choice, matcher)
    assert (request.extraction, request.generation, request.enrichment) == ("rule-based", "rule-based", "sources-only")


def test_a_switch_the_request_sets_wins_over_the_preset() -> None:
    request = GenerateRequest(topic="Optik", preset="best-quality", matcher="hybrid_light", generation="llm")
    assert (request.article_choice, request.matcher, request.generation) == ("llm", "hybrid_light", "llm")


def test_without_a_preset_the_settings_decide() -> None:
    request = GenerateRequest(topic="Optik")
    assert request.preset is None and all(getattr(request, name) is None for name in SWITCHES)


def test_the_audit_names_the_preset(service: CompendiumService) -> None:
    named = service.generate(GenerateRequest(topic="Geometrische", parts=["world"], preset="llm-free"))
    assert named.audit.preset == "llm-free" and named.audit.llm is None
    assert service.generate(GenerateRequest(topic="Geometrische", parts=["world"])).audit.preset is None


def test_the_balanced_preset_lets_the_llm_choose_the_article(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service, "llm", make_gateway(FakeBApi(by_prompt({"wahl": 3, "titel": ""})), per_request=100_000)
    )
    result = service.generate(GenerateRequest(topic="Geometrische", parts=["world"], preset="balanced"))
    assert result.resolution.method == "llm" and result.audit.matcher == "hybrid_light"


def test_a_preset_without_an_llm_falls_back_and_says_so(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Geometrische", parts=["world"], preset="best-quality"))
    assert result.audit.llm is not None and "nicht konfiguriert" in result.audit.llm["note"]
    assert result.audit.matcher == "hybrid_light" and result.audit.llm["article_choice"]["used"] == "rule-based"


def test_the_knowledge_request_takes_the_article_choice_of_the_preset() -> None:
    assert KnowledgeRequest(topic="Optik", preset="balanced").article_choice == "llm"
    assert KnowledgeRequest(topic="Optik", preset="llm-free").article_choice == "rule-based"
    assert KnowledgeRequest(topic="Optik", preset="best-quality", article_choice="rule-based").article_choice == (
        "rule-based"
    )
    assert KnowledgeRequest(topic="Optik").article_choice is None


def test_the_cli_takes_the_preset(
    cli_env: Path,  # noqa: F811 - the fixture imported above
    sample_zims: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_file = cli_env / "optik.md"
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    assert main(["generate", "--topic", "Optik", "--preset", "balanced", "--out", str(out_file), *zim_args]) == 0
    err = capsys.readouterr().err
    assert "Stufe: balanced" in err and "nicht konfiguriert" in err


def test_the_cli_rejects_an_unknown_preset(cli_env: Path) -> None:  # noqa: F811
    with pytest.raises(SystemExit) as info:
        main(["generate", "--topic", "Optik", "--preset", "turbo"])
    assert info.value.code == 2
