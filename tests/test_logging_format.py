"""LOG_FORMAT=json writes one JSON object per log line (audit 2026-09-18, OPS-03).

A log collector reads the plain lines only with a pattern of its own, and a traceback spans many lines. As JSON every
event is one line with its time, level, logger, request id and message, the traceback inside it.
"""

from __future__ import annotations

import json
import logging
from logging.config import dictConfig

import pytest
from uvicorn.config import LOGGING_CONFIG

from app.logging import configure_logging
from app.settings import Settings
from tests.test_threads_context import in_a_request


UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configured(monkeypatch: pytest.MonkeyPatch, *format_: str, uvicorn: bool = False) -> None:
    """configure_logging on a root logger without the handlers pytest gave it, as in production; with ``uvicorn``
    after uvicorn's own logging, as it sets it up in every worker before the app is built. In the test, not in a
    fixture: pytest adds its capturing handler again when the test starts, and a root with a handler is left as it
    is. Levels, handlers and propagation come back afterwards."""
    root, httpx_logger = logging.getLogger(), logging.getLogger("httpx")
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", root.level)
    monkeypatch.setattr(httpx_logger, "level", httpx_logger.level)
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        for attribute in ("handlers", "propagate", "level"):
            monkeypatch.setattr(
                logger, attribute, list(logger.handlers) if attribute == "handlers" else getattr(logger, attribute)
            )
    if uvicorn:
        dictConfig(LOGGING_CONFIG)
    configure_logging("INFO", *format_)


def lines_with(text: str, capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [line for line in capsys.readouterr().out.splitlines() if text in line]


def test_a_json_line_names_time_level_logger_request_and_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configured(monkeypatch, "json")
    in_a_request("rid-15", lambda: logging.getLogger("app.probe").warning("Probe %s", 1))

    [line] = lines_with("Probe", capsys)
    event = json.loads(line)

    assert {key: event[key] for key in ("level", "logger", "request_id", "message")} == {
        "level": "WARNING",
        "logger": "app.probe",
        "request_id": "rid-15",
        "message": "Probe 1",
    }
    assert event["time"].endswith("Z")


def test_an_error_keeps_its_traceback_inside_its_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configured(monkeypatch, "json")
    try:
        raise ValueError("kaputt")
    except ValueError:
        logging.getLogger("app.probe").exception("Probe fehlgeschlagen")

    [line] = lines_with("Probe fehlgeschlagen", capsys)

    assert "ValueError: kaputt" in json.loads(line)["exc"]


def test_uvicorn_writes_its_access_and_error_lines_as_json_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """uvicorn gives its loggers handlers of their own: its access line for every request (the healthcheck every 30 s)
    and its traceback of an error stayed plain text between the JSON lines (review of 2026-10-08)."""
    configured(monkeypatch, "json", uvicorn=True)
    access = logging.getLogger("uvicorn.access")
    access.info('%s - "%s %s HTTP/%s" %d', "172.18.0.1:4711", "GET", "/health", "1.1", 200)
    try:
        raise RuntimeError("kaputt")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")

    written = capsys.readouterr()
    events = [json.loads(line) for line in written.out.splitlines()]

    assert [(event["logger"], event["message"]) for event in events] == [
        ("uvicorn.access", '172.18.0.1:4711 - "GET /health HTTP/1.1" 200'),
        ("uvicorn.error", "Exception in ASGI application"),
    ]
    assert "RuntimeError: kaputt" in events[1]["exc"] and written.err == ""


def test_the_plain_line_stays_the_default(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    configured(monkeypatch)
    logging.getLogger("app.probe").info("Probe 2")

    [line] = lines_with("Probe 2", capsys)

    assert line.split(" | ")[1:] == ["INFO    ", "app.probe", "-", "Probe 2"]


@pytest.mark.parametrize(("value", "expected"), [(None, "text"), ("", "text"), ("json", "json")])
def test_log_format_is_text_unless_set_to_json(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str
) -> None:
    if value is None:
        monkeypatch.delenv("LOG_FORMAT", raising=False)
    else:
        monkeypatch.setenv("LOG_FORMAT", value)

    assert Settings(_env_file=None).log_format == expected


def test_any_other_log_format_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "xml")

    with pytest.raises(ValueError, match="log_format"):
        Settings(_env_file=None)
