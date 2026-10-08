"""The LLM check of part 2 spends from a budget of its own (D94).

Jan, 2026-10-08: with curricula of more states or levels "das budget für teil 2 eventuell nicht reicht - aber wir
möglichst nichts verlieren wollen". The check rates every element the rules found, about 70 to 85 tokens each (M76:
Demokratie 819 elements, 66,200 tokens); beside part 1 (D93) it drew from the request's budget, so more elements could
take part 1 the room for its writing. Now neither takes from the other, and elements beyond the check's own budget stay
in part 2 unrated, as the rules found them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.requests import GenerateRequest
from app.llm.prompts import get_prompt
from app.service import CompendiumService
from app.settings import Settings
from tests.test_lehrplan_api import write_cache
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

CURRICULUM = get_prompt("curriculum_check").system
REQUEST = GenerateRequest(topic="Optik", parts=["world", "curricula"], subject="Physik", preset="best-quality")


def answer(body: dict[str, Any]) -> str:
    """Rates every element 2; to every other question an answer that decides nothing."""
    if body["messages"][0]["content"].startswith(CURRICULUM):
        return json.dumps({f"e{number}": 2 for number in range(1, 61)})
    return json.dumps({"uebersicht": "Optik", "artikel": []})


@pytest.fixture
def checking(service: CompendiumService, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FakeBApi:
    write_cache(settings.state_dir)
    fake = FakeBApi(answer, cached_tokens=7)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    return fake


def test_part_2_checks_every_element_however_little_the_request_leaves(
    service: CompendiumService, checking: FakeBApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service.settings, "llm_max_tokens_per_request_best_quality", 100)

    result = service.generate(REQUEST)

    llm = result.audit.llm or {}
    check = llm["curriculum_check"]
    assert check["rated"] > 0 and check["answered"] == check["rated"] and not check["fallbacks"]
    assert any("Token-Budget der Anfrage" in reason for reason in llm["matching"]["fallbacks"]), "part 1 had room"


def test_elements_beyond_the_check_budget_stay_unrated_and_part_1_keeps_its_room(
    service: CompendiumService, checking: FakeBApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service.settings, "llm_max_tokens_curriculum_check", 100)

    result = service.generate(REQUEST)

    llm = result.audit.llm or {}
    check = llm["curriculum_check"]
    assert check["answered"] == 0 and check["rated"] > 0
    assert any("Token-Budget der Lehrplanprüfung" in reason for reason in check["fallbacks"])
    assert result.curricula is not None and result.curricula.entries, "the unrated elements stay in part 2"
    assert all(entry["note"] is None for entry in result.curricula.entries)
    assert not any("Token-Budget" in reason for reason in llm["matching"]["fallbacks"])


def test_the_tokens_the_check_read_from_the_cache_count_in_the_audit(
    service: CompendiumService, checking: FakeBApi
) -> None:
    result = service.generate(REQUEST)

    tokens = result.audit.llm_tokens or {}
    assert tokens["cached"] == 7 * tokens["calls"], "every answer read 7 tokens from the cache, the check's as well"
