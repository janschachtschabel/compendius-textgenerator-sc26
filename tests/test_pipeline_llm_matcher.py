"""matcher=llm in the pipeline (D34): the compendium follows the model's assignment and says so."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.compose.assembler import AI_SELECTED_DISCLOSURE
from app.domain.models import SectionStatus
from app.domain.requests import GenerateRequest
from app.llm.prompts import get_prompt
from app.main import create_app
from app.service import CompendiumService
from tests.conftest import make_settings
from tests.test_llm_assignment import PARAGRAPH_RE
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

ASSIGNMENT_PROMPT = get_prompt("paragraph_assignment").tag


def leads_define_the_rest_is_content(body: dict[str, Any]) -> str:
    """The main article's lead goes into the definition, every other paragraph into Fachinhalte."""
    user = body["messages"][1]["content"]
    answer = {
        alias: ["themendefinition" if role == "Hauptartikel" and heading == "Einleitung" else "fachinhalte", 0.9]
        for alias, _title, role, heading in PARAGRAPH_RE.findall(user)
    }
    return json.dumps(answer)


def _content(result: Any) -> list[Any]:
    return [s for s in result.sections if s.slot_key not in {"akteure", "quellen", "glossar"}]


def test_matcher_llm_writes_the_compendium_from_the_models_assignment(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(leads_define_the_rest_is_content)
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=1_000_000))
    result = service.generate(GenerateRequest(topic="Optik", matcher="llm", parts=["world"]))

    assert result.audit.matcher == "llm" and result.frontmatter["matcher"] == "llm"
    assert "matcher_requested" not in result.frontmatter
    assert result.extraction == "rule-based" and result.generation == "rule-based"
    assert result.frontmatter["ai_disclosure"] == AI_SELECTED_DISCLOSURE
    assert result.frontmatter["review"]["status"] == "ki-ausgewählt"
    filled = [s for s in _content(result) if s.text]
    assert {s.slot_key for s in filled} == {"themendefinition", "fachinhalte"}
    assert all(s.status is SectionStatus.LLM_SELECTED for s in filled)

    assert result.audit.llm is not None
    matching = result.audit.llm["matching"]
    assert matching["requested"] == "llm" and matching["used"] == "llm"
    assert matching["answered"] == matching["paragraphs"] > 0 and matching["fallback_paragraphs"] == 0
    assert ASSIGNMENT_PROMPT in result.frontmatter["llm"]["prompts"]
    tokens = result.audit.llm_tokens
    assert tokens is not None and tokens["calls"] == len(fake.bodies) and tokens["total"] == 24 * tokens["calls"]


def test_matcher_llm_without_a_usable_llm_runs_the_default_strategy(service: CompendiumService) -> None:
    assert service.llm is None  # the test settings keep the b-api off
    result = service.generate(GenerateRequest(topic="Optik", matcher="llm", parts=["world"]))
    default = service.generate(GenerateRequest(topic="Optik", parts=["world"]))

    assert result.audit.matcher == service.settings.matcher_default == result.frontmatter["matcher"]
    assert result.frontmatter["matcher_requested"] == "llm"
    assert result.frontmatter["review"]["status"] == "maschinell-extraktiv"
    assert result.audit.llm is not None and "nicht konfiguriert" in result.audit.llm["note"]
    assert result.audit.llm["matching"]["requested"] == "llm" and result.audit.llm["matching"]["used"] == "rule-based"
    assert [s.text for s in result.sections] == [s.text for s in default.sections]


def test_the_strategies_list_the_llm_matcher_with_its_cost(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(sample_zims.values(), tmp_path)))
    strategies = {s["id"]: s for s in client.get("/api/v2/matching/strategies").json()}
    assert strategies["llm"]["hardware"] == "b-api" and not strategies["llm"]["recommended"]
    assert strategies["hybrid_light"]["recommended"]


def test_llm_cannot_be_the_default_strategy(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    # The default strategy is what matcher=llm falls back on; it has to run without the b-api
    settings = make_settings(sample_zims.values(), tmp_path, matcher_default="llm")
    with pytest.raises(ValueError, match="MATCHER_DEFAULT"):
        create_app(settings)
