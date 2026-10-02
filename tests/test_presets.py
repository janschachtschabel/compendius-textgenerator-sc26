"""The profiles (``preset``) choose the methods of the service (D41, D52).

Jan, 2026-09-25: four profiles. llm-free uses no LLM; balanced lets it find the article of the topic while the rules
assign the paragraphs; best-quality lets it assign them as well; best-quality-generated does everything with it and
completes the text from the model's own knowledge, marked as such, and rewrites it to read well. Jan, 2026-10-01
(D69): a fifth, best-coverage-generated, writes every block about the topic as asked, from the model's own knowledge
where the sources say nothing. balanced is the default (PRESET_DEFAULT). A switch the request sets wins over the
profile. What needs an LLM on a server without one (LLM_ENABLED, B_API_KEY) is refused with a 503 that says so,
instead of quietly running the rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from app.api.v2.knowledge import KnowledgeRequest
from app.cli import main
from app.compendium.errors import LlmNotConfiguredError
from app.domain.requests import PRESET_TARGET_LENGTH, PRESETS, GenerateRequest, Preset, default_preset, with_profile
from app.main import create_app
from app.service import CompendiumService
from app.settings import Settings
from tests.conftest import make_settings
from tests.test_article_choice import by_prompt
from tests.test_cli_generate import cli_env  # noqa: F401 - the fixture of the CLI tests
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

SWITCHES = ("article_choice", "matcher", "extraction", "generation", "enrichment", "model_knowledge_check")
PART_2_SWITCHES = ("curriculum_check",)  # D58; its values per profile: tests/test_curriculum_check.py


def test_the_shipped_default_profile_is_balanced() -> None:
    # Jan, 2026-09-25: the profile that uses the LLM sparingly is the standard; the tests run on llm-free (conftest)
    assert Settings(_env_file=None).preset_default == "balanced"


def test_an_unknown_default_profile_is_refused_with_the_settings(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="preset_default"):
        make_settings(sample_zims.values(), tmp_path, preset_default="turbo")


def test_the_presets_are_the_values_of_the_field() -> None:
    assert list(PRESETS) == list(get_args(Preset))
    assert list(PRESETS) == [
        "llm-free",
        "balanced",
        "best-quality",
        "best-quality-generated",
        "best-coverage-generated",
    ]
    assert all(set(values) == {*SWITCHES, *PART_2_SWITCHES} for values in PRESETS.values())


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("llm-free", ("rule-based", "hybrid_light", "rule-based", "rule-based", "sources-only", "rule-based")),
        ("balanced", ("llm", "hybrid_light", "rule-based", "rule-based", "sources-only", "rule-based")),
        ("best-quality", ("llm-thorough", "llm", "rule-based", "rule-based", "sources-only", "rule-based")),
        ("best-quality-generated", ("llm-thorough", "llm", "rule-based", "llm", "model-knowledge", "rule-based")),
        (
            "best-coverage-generated",
            ("llm-thorough", "llm", "rule-based", "llm", "model-knowledge-full", "rule-based"),
        ),
    ],
)
def test_a_preset_sets_every_switch_of_part_1(preset: str, expected: tuple[str, ...]) -> None:
    request = GenerateRequest(topic="Optik", preset=preset)
    assert tuple(getattr(request, name) for name in SWITCHES) == expected


@pytest.mark.parametrize("preset", list(PRESETS))
def test_every_profile_asks_for_30000_characters_unless_the_request_names_a_length(preset: str) -> None:
    """Jan, 2026-10-01 (D70): compendium texts may be long and complete - 30,000 characters in every profile for now,
    a profile may set its own, and a request that names a length keeps it."""
    assert GenerateRequest(topic="Optik", preset=preset).target_length == 30_000
    assert GenerateRequest(topic="Optik", preset=preset, target_length=8_000).target_length == 8_000


def test_the_length_of_a_profile_fills_in_for_its_own_and_for_the_servers_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PRESET_TARGET_LENGTH, "balanced", 20_000)
    assert GenerateRequest(topic="Optik", preset="balanced").target_length == 20_000
    assert with_profile(GenerateRequest(topic="Optik"), "balanced").target_length == 20_000
    assert with_profile(GenerateRequest(topic="Optik", target_length=9_000), "balanced").target_length == 9_000


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


@pytest.mark.parametrize(
    ("configured", "llm", "expected"),
    [
        ("balanced", True, "balanced"),
        ("best-quality", True, "best-quality"),
        ("llm-free", True, "llm-free"),
        ("balanced", False, "llm-free"),
        ("best-quality-generated", False, "llm-free"),
        ("llm-free", False, "llm-free"),
    ],
)
def test_the_default_profile_is_the_configured_one_while_an_llm_is(
    configured: Preset, llm: bool, expected: str
) -> None:
    """Jan, 2026-09-30 (D68): with an LLM a request without a profile takes PRESET_DEFAULT, shipped balanced; without
    one llm-free, so that the service always answers at least with the rules."""
    assert default_preset(configured, llm) == expected


def test_the_service_takes_the_default_of_its_settings_while_it_has_an_llm(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service.settings, "preset_default", "best-quality")
    assert service.llm is None  # the test settings keep the b-api off
    without = service.default_preset

    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi()))

    assert (without, service.default_preset) == ("llm-free", "best-quality")


def test_without_an_llm_a_request_without_a_profile_runs_llm_free(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """D68: before, a server without an LLM refused every request without a profile, since PRESET_DEFAULT is balanced.
    A profile the request names itself is its wish and still refused without the LLM."""
    with TestClient(create_app(make_settings(sample_zims.values(), tmp_path, preset_default="balanced"))) as client:
        bare = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"]})
        named = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"], "preset": "balanced"})
        knowledge = client.post("/api/v2/knowledge", json={"topic": "Optik"})
    assert bare.status_code == 200 and bare.json()["audit"]["preset"] == "llm-free"
    assert named.status_code == 503 and "Profil balanced" in named.json()["detail"]
    assert knowledge.status_code == 200 and knowledge.json()["article_choice"] is None  # the rules chose, no LLM block


def test_a_switch_without_a_profile_is_refused_for_the_missing_llm_not_for_preset_default(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    """D68: without an LLM a request without a profile runs llm-free whatever PRESET_DEFAULT says, so the 503 for a
    switch the request names blames the missing LLM. It said "Standardprofil llm-free (PRESET_DEFAULT)" while
    PRESET_DEFAULT was balanced, and told the caller to choose llm-free, the profile it already had."""
    with TestClient(create_app(make_settings(sample_zims.values(), tmp_path, preset_default="balanced"))) as client:
        refused = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"], "extraction": "llm"})
    detail = refused.json()["detail"]
    assert refused.status_code == 503 and "extraction=llm" in detail and "LLM_ENABLED" in detail
    assert "PRESET_DEFAULT" not in detail and "ohne LLM gilt llm-free" in detail
    assert "Profil llm-free wählen" not in detail


def test_the_refusal_names_the_part_of_the_llm_that_is_missing(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM_ENABLED with an empty B_API_KEY leaves the service without an LLM as well; the 503 said LLM_ENABLED was
    not active, the one setting that was right."""
    keyless = service.settings.model_copy(update={"llm_enabled": True, "b_api_key": ""})
    monkeypatch.setattr(service, "settings", keyless)
    with pytest.raises(LlmNotConfiguredError) as refused:
        service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="balanced"))
    message = str(refused.value)
    assert message.startswith("B_API_KEY ist leer") and "Profil balanced" in message
    assert "LLM_ENABLED ist nicht aktiv" not in message


def test_a_template_default_that_names_no_template_leaves_sc26(
    sample_zims: dict[str, Path], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """D68: a TEMPLATE_DEFAULT that names no template took every request without template_id down with a 404. Those
    take sc26 now, and the start says so; a request that names the missing template is still its 404."""
    with caplog.at_level("WARNING"):
        app = create_app(make_settings(sample_zims.values(), tmp_path, template_default="missing"))
    with TestClient(app) as client:
        bare = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"]})
        named = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["world"], "template_id": "missing"})
    assert bare.status_code == 200 and bare.json()["template_id"] == "sc26"
    assert named.status_code == 404
    assert "TEMPLATE_DEFAULT" in caplog.text


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
