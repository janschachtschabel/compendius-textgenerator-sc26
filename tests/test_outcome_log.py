"""One line per compendium with what the request got (logging review of 2026-10-08).

A best-quality-generated compendium that came back extractive after 300 s left the access line and nothing else: no
sign that the deadline or the budget cut the writing, nor how much of it. A call skipped for time or budget writes
no line of its own; the line of the request counts them by cause.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.compendium.llm_report import NOTHING_CONTRIBUTED
from app.domain.requests import GenerateRequest
from app.main import create_app
from app.observability.outcome import fallback_causes, log_compendium
from app.service import CompendiumService
from tests.conftest import make_settings


def test_fallbacks_are_counted_by_stage_and_cause() -> None:
    llm = {
        "generation": {"fallbacks": {"sc26_1": "Token-Budget der Anfrage erschöpft (900 Tokens nötig, 10 frei)"}},
        "matching": {"fallbacks": {"Zeitbudget der Anfrage erschöpft (REQUEST_TIMEOUT_S)": 12}},  # paragraphs
        "extraction": {
            "fallbacks": {
                "a": "b-api: Zeitbudget der Anfrage erschöpft, während der Aufruf auf einen freien Platz wartete",
                "b": "b-api: b-api antwortete HTTP 500",
            }
        },
        "curriculum_check": {"fallbacks": {}, "fallback": "Tagesbudget erschöpft (5 Tokens nötig, 0 frei)"},
        "article_choice": {"fallback": "Antwort nicht lesbar"},
        "note": "not a stage",
    }

    assert fallback_causes(llm) == {
        "generation": {"budget": 1},
        "matching": {"time": 12},
        "extraction": {"b-api": 1, "time": 1},
        "curriculum_check": {"budget": 1},
        "article_choice": {"other": 1},
    }


def test_a_compendium_whose_budget_cut_llm_work_is_a_warning(
    service: CompendiumService, caplog: pytest.LogCaptureFixture
) -> None:
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))
    reason = "Token-Budget der Anfrage erschöpft (900 Tokens nötig, 10 frei)"
    result.audit.llm = {"generation": {"used": "llm", "fallbacks": {"sc26_1": reason}}}

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        log_compendium(result)

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert "LLM generation" in record.getMessage() and "fallbacks generation budget=1" in record.getMessage()


def test_a_compendium_through_the_api_writes_its_line(
    sample_zims: dict[str, Path], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = TestClient(create_app(make_settings(sample_zims.values(), tmp_path / "state")))

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        assert client.post("/api/v2/compendium", json={"topic": "Optik", "preset": "llm-free"}).status_code == 200

    [record] = [record for record in caplog.records if record.name == "app.observability.outcome"]
    assert record.levelno == logging.INFO
    message = record.getMessage()
    assert message.startswith("compendium 'Optik': llm-free, ") and "LLM none" in message and " ms" in message
    fields = record.fields  # type: ignore[attr-defined]
    assert fields["preset"] == "llm-free" and fields["fallbacks"] == {} and fields["llm_calls"] == 0


@pytest.mark.parametrize(
    "note",
    [
        "LLM nicht verfügbar (b-api nach wiederholten Fehlern vorübergehend ausgesetzt); Regelmodus verwendet",
        "LLM nicht konfiguriert (LLM_ENABLED, B_API_KEY); Regelmodus verwendet",
    ],
)
def test_a_compendium_that_wanted_an_unavailable_llm_is_a_warning_with_the_reason(
    service: CompendiumService, caplog: pytest.LogCaptureFixture, note: str
) -> None:
    """A best-quality request while the breaker was open ran on the rules alone; its line said "LLM none, fallbacks
    none", and only the audit named the reason (logging review of 2026-10-08)."""
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))
    result.audit.llm = {"note": note, "generation": {"used": "rule-based", "fallbacks": {}}}

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        log_compendium(result)

    [record] = caplog.records
    assert record.levelno == logging.WARNING and record.getMessage().endswith(f"; {note}")


def test_a_compendium_the_llm_contributed_nothing_to_stays_an_info_line(
    service: CompendiumService, caplog: pytest.LogCaptureFixture
) -> None:
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))
    result.audit.llm = {"note": NOTHING_CONTRIBUTED, "generation": {"used": "rule-based", "fallbacks": {}}}

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        log_compendium(result)

    [record] = caplog.records
    assert record.levelno == logging.INFO and NOTHING_CONTRIBUTED not in record.getMessage()
