"""The profiles (``preset``) choose the methods of the service (D41, D52).

Jan, 2026-09-25: four profiles. llm-free uses no LLM; balanced lets it find the article of the topic while the rules
assign the paragraphs; best-quality lets it assign them as well; best-quality-generated does everything with it and
completes the text from the model's own knowledge, marked as such, and rewrites it to read well. balanced is the
default (PRESET_DEFAULT). A switch the request sets wins over the profile. What needs an LLM on a server without one
(LLM_ENABLED, B_API_KEY) is refused with a 503 that says so, instead of quietly running the rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from app.api.v2.knowledge import KnowledgeRequest
from app.cli import main
from app.domain.requests import PRESETS, GenerateRequest, Preset
from app.main import create_app
from app.service import CompendiumService, LlmNotConfiguredError
from app.settings import Settings
from tests.conftest import make_settings
from tests.test_article_choice import by_prompt
from tests.test_cli_generate import cli_env  # noqa: F401 - the fixture of the CLI tests
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

SWITCHES = ("article_choice", "matcher", "extraction", "generation", "enrichment")
PART_2_SWITCHES = ("curriculum_check",)  # D58; its values per profile: tests/test_curriculum_check.py


def test_the_shipped_default_profile_is_balanced() -> None:
    # Jan, 2026-09-25: the profile that uses the LLM sparingly is the standard; the tests run on llm-free (conftest)
    assert Settings(_env_file=None).preset_default == "balanced"  # type: ignore[call-arg]


def test_an_unknown_default_profile_is_refused_with_the_settings(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="preset_default"):
        make_settings(sample_zims.values(), tmp_path, preset_default="turbo")


def test_the_presets_are_the_values_of_the_field() -> None:
    assert list(PRESETS) == list(get_args(Preset))
    assert list(PRESETS) == ["llm-free", "balanced", "best-quality", "best-quality-generated"]
    assert all(set(values) == {*SWITCHES, *PART_2_SWITCHES} for values in PRESETS.values())


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("llm-free", ("rule-based", "hybrid_light", "rule-based", "rule-based", "sources-only")),
        ("balanced", ("llm", "hybrid_light", "rule-based", "rule-based", "sources-only")),
        ("best-quality", ("llm-thorough", "llm", "rule-based", "rule-based", "sources-only")),
        ("best-quality-generated", ("llm-thorough", "llm", "rule-based", "llm", "model-knowledge")),
    ],
)
def test_a_preset_sets_every_switch_of_part_1(preset: str, expected: tuple[str, ...]) -> None:
    request = GenerateRequest(topic="Optik", preset=preset)  # type: ignore[arg-type]
    assert tuple(getattr(request, name) for name in SWITCHES) == expected


def test_a_switch_the_request_sets_wins_over_the_preset() -> None:
    request = GenerateRequest(topic="Optik", preset="best-quality", matcher="hybrid_light", generation="llm")
    assert (request.article_choice, request.matcher, request.generation) == ("llm-thorough", "hybrid_light", "llm")


def test_without_a_preset_the_default_profile_fills_the_open_switches(service: CompendiumService) -> None:
    assert service.settings.preset_default == "llm-free"  # the offline default of the tests (conftest)
    result = service.generate(GenerateRequest(topic="Geometrische", parts=["world"], matcher="bm25"))
    assert result.audit.preset == "llm-free" and result.audit.matcher == "bm25" and result.audit.llm is None


def test_the_balanced_preset_lets_the_llm_choose_the_article(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service, "llm", make_gateway(FakeBApi(by_prompt({"wahl": 3, "titel": ""})), per_request=100_000)
    )
    result = service.generate(GenerateRequest(topic="Geometrische", parts=["world"], preset="balanced"))
    assert result.resolution.method == "llm" and result.audit.matcher == "hybrid_light"
    assert result.audit.preset == "balanced"


def test_a_profile_that_needs_an_llm_is_refused_without_one(service: CompendiumService) -> None:
    assert service.llm is None  # the test settings keep the b-api off
    with pytest.raises(LlmNotConfiguredError) as refused:
        service.generate(GenerateRequest(topic="Geometrische", parts=["world"], preset="best-quality"))
    message = str(refused.value)
    assert "LLM_ENABLED" in message and "best-quality" in message and "llm-free" in message
    assert "article_choice=llm-thorough" in message and "matcher=llm" in message


def test_a_switch_that_needs_an_llm_is_refused_without_one_as_well(service: CompendiumService) -> None:
    with pytest.raises(LlmNotConfiguredError, match="generation=llm"):
        service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free", generation="llm"))


def test_the_default_profile_needs_an_llm_too_and_the_api_answers_503(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    with TestClient(create_app(make_settings(sample_zims.values(), tmp_path, preset_default="balanced"))) as client:
        refused = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"]})
        free = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"], "preset": "llm-free"})
    assert refused.status_code == 503 and "PRESET_DEFAULT" in refused.json()["detail"]
    assert free.status_code == 200 and free.json()["audit"]["preset"] == "llm-free"


def test_the_knowledge_request_takes_the_article_choice_of_the_preset() -> None:
    assert KnowledgeRequest(topic="Optik", preset="balanced").article_choice == "llm"
    assert KnowledgeRequest(topic="Optik", preset="llm-free").article_choice == "rule-based"
    assert KnowledgeRequest(topic="Optik", preset="best-quality").article_choice == "llm-thorough"  # D61
    assert KnowledgeRequest(topic="Optik", preset="best-quality", article_choice="rule-based").article_choice == (
        "rule-based"
    )
    assert KnowledgeRequest(topic="Optik").article_choice is None  # the endpoint takes the default profile's


def test_the_knowledge_endpoint_refuses_an_llm_profile_without_an_llm(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        refused = client.post("/api/v2/knowledge", json={"topic": "Optik", "preset": "balanced"})
        free = client.post("/api/v2/knowledge", json={"topic": "Optik"})
    assert refused.status_code == 503 and "LLM_ENABLED" in refused.json()["detail"]
    assert free.status_code == 200


def test_the_knowledge_endpoint_refuses_the_thorough_choice_without_an_llm(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        refused = client.post("/api/v2/knowledge", json={"topic": "Optik", "article_choice": "llm-thorough"})
    assert refused.status_code == 503 and "article_choice=llm-thorough" in refused.json()["detail"]


def test_the_cli_takes_the_preset(
    cli_env: Path,  # noqa: F811 - the fixture imported above
    sample_zims: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_file = cli_env / "optik.md"
    zim_args = [arg for path in sample_zims.values() for arg in ("--zim", str(path))]
    assert main(["generate", "--topic", "Optik", "--preset", "llm-free", "--out", str(out_file), *zim_args]) == 0
    assert "Profil: llm-free" in capsys.readouterr().err
    assert main(["generate", "--topic", "Optik", "--preset", "balanced", "--out", str(out_file), *zim_args]) == 1
    assert "LLM_ENABLED" in capsys.readouterr().err


def test_the_cli_rejects_an_unknown_preset(cli_env: Path) -> None:  # noqa: F811
    with pytest.raises(SystemExit) as info:
        main(["generate", "--topic", "Optik", "--preset", "turbo"])
    assert info.value.code == 2
