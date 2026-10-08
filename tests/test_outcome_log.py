"""One line per compendium, and per answer of the other endpoints that asked an LLM, with what the request got
(logging review of 2026-10-08).

A best-quality-generated compendium that came back extractive after 300 s left the access line and nothing else: no
sign that the deadline or the budget cut the writing, nor how much of it. A call skipped for time or budget writes
no line of its own; the line of the request counts them by cause.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.compendium.llm_report import NOTHING_CONTRIBUTED
from app.domain.requests import GenerateRequest
from app.llm.call import TIME_UP
from app.main import create_app
from app.observability.outcome import fallback_causes, log_answer, log_compendium
from app.service import CompendiumService
from tests.conftest import make_settings

HELD_BACK = "LLM nicht verfügbar (b-api nach wiederholten Fehlern vorübergehend ausgesetzt); Regelmodus verwendet"


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


def test_the_article_choice_counts_the_fallbacks_of_its_check_and_of_its_articles() -> None:
    """The article choice gives three reasons: its own, the check of the full-text hits and the question for the
    articles of a topic (D63). The line read the first alone, and a budget that cut the other two went unsaid."""
    llm = {
        "article_choice": {
            "used": "rule-based",
            "fallback": None,
            "hits_fallback": "Token-Budget der Anfrage erschöpft (900 Tokens nötig, 10 frei)",
            "articles_fallback": TIME_UP,
        }
    }

    assert fallback_causes(llm) == {"article_choice": {"budget": 1, "time": 1}}


def test_an_llm_that_was_not_there_is_a_cause_of_its_own() -> None:
    """The breaker's reason names the b-api, but the stage never asked it: no failure of the b-api."""
    llm = {"curriculum_check": {"used": "rule-based", "fallbacks": {}, "fallback": HELD_BACK}}

    assert fallback_causes(llm) == {"curriculum_check": {"unavailable": 1}}


def test_an_answer_that_asked_an_llm_writes_the_line_of_a_compendium(caplog: pytest.LogCaptureFixture) -> None:
    """/qa, /entities, /knowledge and the curriculum search said what their LLM did only in the answer (logging
    review of 2026-10-08, H2); their line has the compendium's form, without its parts and duration."""
    llm: dict[str, Any] = {
        "note": None,
        "article_choice": {"used": "llm", "fallback": None},
        "curriculum_check": {"used": "llm", "fallbacks": {}, "fallback": None},
    }

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        log_answer("curriculum search", "Optik", "best-quality", llm, {"calls": 3, "total": 1234})

    [record] = caplog.records
    assert record.levelno == logging.INFO
    assert record.getMessage() == (
        "curriculum search 'Optik': best-quality, LLM article_choice,curriculum_check, 3 calls, 1234 tokens, "
        "fallbacks none"
    )
    assert record.fields == {  # type: ignore[attr-defined]
        "answer": "curriculum search",
        "topic": "Optik",
        "preset": "best-quality",
        "llm": ["article_choice", "curriculum_check"],
        "llm_calls": 3,
        "llm_tokens": 1234,
        "fallbacks": {},
        "llm_unavailable": None,
    }


def test_an_answer_whose_llm_was_not_there_is_a_warning_that_names_the_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Held back by the breaker, the entities came from the rules; since the breaker logs its change once, nothing
    tied the request to it (logging review of 2026-10-08)."""
    llm = {"naming": {"used": "rule-based", "fallback": HELD_BACK}}

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        log_answer("entities", None, "balanced", llm, None)

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        f"entities: balanced, LLM none, 0 calls, 0 tokens, fallbacks naming unavailable=1; {HELD_BACK}"
    )
    assert record.fields["topic"] is None and record.fields["llm_unavailable"] == HELD_BACK  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("reason", "level"),
    [
        (TIME_UP, logging.WARNING),
        ("Token-Budget der Anfrage erschöpft (900 Tokens nötig, 10 frei)", logging.WARNING),
        ("b-api: b-api antwortete HTTP 500", logging.INFO),  # the failed call wrote its own WARNING
        ("LLM lieferte keine verwertbaren Paare; Regelmodus verwendet", logging.INFO),
    ],
)
def test_an_answer_is_a_warning_by_the_rule_of_a_compendium(
    caplog: pytest.LogCaptureFixture, reason: str, level: int
) -> None:
    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        log_answer("qa", "Optik", "best-quality", {"pairs": {"used": "rule-based", "fallback": reason}}, None)

    [record] = caplog.records
    assert record.levelno == level


def test_a_compendium_line_names_what_answered_for_a_log_collector(
    service: CompendiumService, caplog: pytest.LogCaptureFixture
) -> None:
    """Its fields carry the name the lines of the other endpoints carry, so a collector counts all of them alike."""
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        log_compendium(result)

    [record] = caplog.records
    assert record.fields["answer"] == "compendium"  # type: ignore[attr-defined]


def test_a_compendium_whose_curriculum_check_found_no_llm_names_the_reason(
    service: CompendiumService, caplog: pytest.LogCaptureFixture
) -> None:
    """Part 2 alone with curriculum_check=llm and the rules choosing the article: the note said only that the LLM had
    contributed nothing, the check's reason said why, and the line stayed an INFO."""
    result = service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))
    result.audit.llm = {
        "note": NOTHING_CONTRIBUTED,
        "curriculum_check": {"used": "rule-based", "fallbacks": {}, "fallback": HELD_BACK},
    }

    with caplog.at_level(logging.INFO, logger="app.observability.outcome"):
        log_compendium(result)

    [record] = caplog.records
    assert record.levelno == logging.WARNING and record.getMessage().endswith(f"; {HELD_BACK}")
