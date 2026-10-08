"""LOG_FORMAT=json writes one JSON object per log line (audit 2026-09-18, OPS-03).

A log collector reads the plain lines only with a pattern of its own, and a traceback spans many lines. As JSON every
event is one line with its time, level, logger, request id and message, the traceback inside it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from logging.config import dictConfig

import pytest
from uvicorn.config import LOGGING_CONFIG

from app.logging import configure_logging
from app.settings import Settings
from tests.test_threads_context import in_a_request

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configured(monkeypatch: pytest.MonkeyPatch, *format_: str, uvicorn: bool = False, level: str = "INFO") -> None:
    """configure_logging on a root logger without the handlers pytest gave it, as in production; with ``uvicorn``
    after uvicorn's own logging, as it sets it up in every worker before the app is built. In the test, not in a
    fixture: pytest adds its capturing handler again when the test starts, and a root with a handler is left as it
    is. Levels, handlers and propagation come back afterwards."""
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", root.level)
    for name in ("httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.getLogger(name).level)
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        for attribute in ("handlers", "propagate", "level"):
            monkeypatch.setattr(
                logger, attribute, list(logger.handlers) if attribute == "handlers" else getattr(logger, attribute)
            )
    if uvicorn:
        dictConfig(LOGGING_CONFIG)
    configure_logging(level, *format_)


def lines_with(text: str, capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if text in line]


def test_log_lines_go_to_stderr_so_a_report_on_stdout_stays_readable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`compendium zim sync --offline > report.json` began with a log line, and the report no longer parsed (logging
    review of 2026-10-08): the commands print their reports on stdout, the log goes to stderr; Docker keeps both."""
    configured(monkeypatch)
    logging.getLogger("app.probe").info("Probe 3")
    sys.stdout.write('{"report": 1}\n')  # as the commands print their reports

    written = capsys.readouterr()

    assert json.loads(written.out) == {"report": 1} and "Probe 3" in written.err


def test_a_json_line_names_time_level_process_logger_request_and_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configured(monkeypatch, "json")
    in_a_request("rid-15", lambda: logging.getLogger("app.probe").warning("Probe %s", 1))

    [line] = lines_with("Probe", capsys)
    event = json.loads(line)

    assert {key: event[key] for key in ("level", "pid", "logger", "request_id", "message")} == {
        "level": "WARNING",
        "pid": os.getpid(),
        "logger": "app.probe",
        "request_id": "rid-15",
        "message": "Probe 1",
    }
    assert event["time"].endswith("Z")


def test_the_fields_of_an_event_become_fields_of_its_json_object(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A collector reads the status of a request without a pattern of its own; the fields never replace the line's own
    (logging review of 2026-10-08)."""
    configured(monkeypatch, "json")
    fields = {"status": 418, "duration_ms": 12, "level": "forged"}
    logging.getLogger("app.probe").info("GET /x 418 12 ms", extra={"fields": fields})

    [line] = lines_with("GET /x", capsys)
    event = json.loads(line)

    assert (event["status"], event["duration_ms"], event["level"]) == (418, 12, "INFO")


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
    events = [json.loads(line) for line in written.err.splitlines()]

    assert [(event["logger"], event["message"]) for event in events] == [
        ("uvicorn.access", '172.18.0.1:4711 - "GET /health HTTP/1.1" 200'),
        ("uvicorn.error", "Exception in ASGI application"),
    ]
    assert "RuntimeError: kaputt" in events[1]["exc"] and written.out == ""


def test_uvicorn_s_lines_name_time_logger_and_request_in_the_plain_format_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """In the plain format uvicorn kept its own lines - its access line, its start, a worker that died - without time,
    logger or request id, so grep for the id of a refused request found nothing (logging review of 2026-10-08)."""
    configured(monkeypatch, uvicorn=True)
    access = logging.getLogger("uvicorn.access")
    in_a_request("rid-21", lambda: access.info('%s - "%s %s HTTP/%s" %d', "172.18.0.1:4711", "GET", "/x", "1.1", 401))

    [line] = lines_with('"GET /x HTTP/1.1"', capsys)

    assert line.split(" | ")[1:] == [
        "INFO    ",
        str(os.getpid()),
        "uvicorn.access",
        "rid-21",
        '172.18.0.1:4711 - "GET /x HTTP/1.1" 401',
    ]


def test_at_debug_the_transport_of_the_http_client_stays_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """At LOG_LEVEL=DEBUG httpcore wrote twelve lines per outgoing request, every response header among them, so the
    session cookie edu-sharing hands the configured account (logging review of 2026-10-08); httpx was quiet already."""
    configured(monkeypatch, level="DEBUG")

    assert logging.getLogger("httpcore.http11").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("app.sources").getEffectiveLevel() == logging.DEBUG


def test_the_plain_line_stays_the_default(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The process is named: with two workers their lines interleave, and uvicorn names a worker that died by its pid
    (logging review of 2026-10-08)."""
    configured(monkeypatch)
    logging.getLogger("app.probe").info("Probe 2")

    [line] = lines_with("Probe 2", capsys)

    assert line.split(" | ")[1:] == ["INFO    ", str(os.getpid()), "app.probe", "-", "Probe 2"]


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "INFO"), ("", "INFO"), ("debug", "DEBUG"), (" Warn ", "WARNING"), ("error", "ERROR")],
)
def test_log_level_takes_any_case_and_warn(monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str) -> None:
    if value is None:
        monkeypatch.delenv("LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("LOG_LEVEL", value)

    assert Settings(_env_file=None).log_level == expected


@pytest.mark.parametrize("value", ["verbose", "trace", "INF0"])
def test_an_unknown_log_level_is_refused_at_the_start(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """An unknown level passed the settings: the updaters stopped at their start with "Unknown level", and the API's
    workers raised while the app was built and were started again without end, the container "Up" all the while
    (logging review of 2026-10-08). Now the start command stops before uvicorn, with the setting's name."""
    monkeypatch.setenv("LOG_LEVEL", value)

    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings(_env_file=None)
