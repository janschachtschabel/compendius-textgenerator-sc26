"""Request ids and error capture (PLAN.md 9, audit OPS-03): every answer and every log line names its request."""

from __future__ import annotations

import contextvars
import logging
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.logging import MAX_REQUEST_ID_CHARS, REQUEST_ID_HEADER, _RequestIdFilter, current_request_id
from app.logging import set_request_id as set_in_this_context
from app.main import create_app
from tests.conftest import make_settings


def set_request_id(value: str | None) -> str:
    """``app.logging.set_request_id`` in a context of its own: the id it sets stayed behind in the test's context and
    named the lines of the tests after it."""
    return contextvars.copy_context().run(set_in_this_context, value)


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("rid") / "state")
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaputt")

    @app.get("/boom/{tail}")
    def boom_with(tail: str) -> None:
        raise RuntimeError("kaputt")

    @app.get("/refused")
    def refused() -> None:
        raise HTTPException(status_code=418, detail="nein")

    return TestClient(app, raise_server_exceptions=False)


def test_every_answer_carries_a_request_id(client: TestClient) -> None:
    first = client.get("/health")
    second = client.get("/health")
    assert first.headers[REQUEST_ID_HEADER] and second.headers[REQUEST_ID_HEADER]
    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


def test_an_id_from_the_caller_is_kept(client: TestClient) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: "abc-123"})
    assert response.headers[REQUEST_ID_HEADER] == "abc-123"
    long_one = client.get("/health", headers={REQUEST_ID_HEADER: "x" * 200})
    assert 0 < len(long_one.headers[REQUEST_ID_HEADER]) <= 64  # a header is caller input


def test_an_unexpected_error_is_logged_and_named(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.handler.addFilter(_RequestIdFilter())  # the field the service's own handler gives every line
    with caplog.at_level(logging.ERROR):
        response = client.get("/boom", headers={REQUEST_ID_HEADER: "rid-7"})
    assert response.status_code == 500
    body = response.json()
    assert body["request_id"] == "rid-7" and "rid-7" in response.headers[REQUEST_ID_HEADER]
    assert "kaputt" not in body["detail"], "the caller learns nothing about the internals"
    [error] = caplog.records
    assert error.request_id == "rid-7" and "kaputt" in caplog.text  # type: ignore[attr-defined]


def test_a_refusal_keeps_its_status_and_detail(client: TestClient) -> None:
    response = client.get("/refused", headers={REQUEST_ID_HEADER: "rid-8"})
    assert response.status_code == 418 and response.json()["detail"] == "nein"
    assert response.headers[REQUEST_ID_HEADER] == "rid-8"


def test_outside_a_request_there_is_no_id() -> None:
    assert current_request_id() == "-"


def test_a_long_request_id_is_cut_before_it_is_split() -> None:
    """The whole header was split into words before the cut to 64 characters: 12 MB cost 0.25 s and 219 MB on the
    event loop (audit 2026-09-28, SE-19)."""

    class WholeHeader(str):
        def split(self, *args: object, **kwargs: object) -> list[str]:
            raise AssertionError("the whole header value was split")

    assert set_request_id(WholeHeader("a" * 1_000_000)) == "a" * MAX_REQUEST_ID_CHARS
    assert set_request_id("  abc-123\n\t ") == "abc-123"


def test_an_id_keeps_only_the_signs_ids_are_written_with(client: TestClient) -> None:
    """ESC, BEL and DEL of a caller's id reached every log line of its request and the header of the answer, which h11
    lets through; a space and "|" forged the fields of a log line (audit 2026-09-29, S4)."""
    response = client.get("/refused", headers={REQUEST_ID_HEADER: "abc\x1b[31mRED\x1b[0m\x07def\x7f"})
    assert response.headers[REQUEST_ID_HEADER] == "abc31mRED0mdef"
    assert set_request_id("abc\x9bdef") == "abcdef"  # 0x9b, as the header arrives in latin-1: a C1 terminal's CSI
    assert set_request_id("rid | ERROR | forged") == "ridERRORforged"
    uuid, traceparent, others = (
        "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "00-0af7651916cd-b7ad6b71-01",
        "R=1-a/b+c_d.e:f@g",
    )
    assert [set_request_id(kept) for kept in (uuid, traceparent, others)] == [uuid, traceparent, others]
    made = set_request_id("\x1b\x07 |")  # nothing of it is kept: a new id instead of an empty one
    assert len(made) == 12 and made.isalnum()


def access_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records if record.name == "app.api.request_log" and record.levelno == logging.INFO
    ]


def test_every_request_is_logged_once_with_its_status_and_duration(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """uvicorn's access line was the only trace of most requests: without duration, in the plain format without time
    or request id, and not written at all when the client had gone (logging review of 2026-10-08)."""
    with caplog.at_level(logging.INFO, logger="app.api.request_log"):
        client.get("/refused?x=1", headers={REQUEST_ID_HEADER: "rid-9"})

    [record] = access_lines(caplog)

    assert record.getMessage().startswith("GET /refused?x=1 418 ") and record.getMessage().endswith(" ms")
    fields = record.fields  # type: ignore[attr-defined]
    assert {key: fields[key] for key in ("method", "path", "status", "client")} == {
        "method": "GET",
        "path": "/refused?x=1",
        "status": 418,
        "client": "testclient",
    }
    assert isinstance(fields["duration_ms"], int)


def test_a_probe_that_answers_writes_no_line(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    """The healthcheck every 30 s and the scrape of Prometheus made most lines of a quiet server (188 of 224 in the
    dev container); a probe that fails is still logged."""
    with caplog.at_level(logging.INFO, logger="app.api.request_log"):
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200

    assert access_lines(caplog) == []


def test_an_unexpected_error_is_logged_once_with_its_cause_in_the_first_line(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The handler logged the error, starlette raised it on and uvicorn logged it again, each traceback with the
    frames of three middlewares twice and an ExceptionGroup in front of the cause; grep for the request id found the
    header line, the cause 190 lines further down (logging review of 2026-10-08)."""
    with caplog.at_level(logging.INFO):
        response = client.get("/boom", headers={REQUEST_ID_HEADER: "rid-10"})

    assert response.status_code == 500 and response.json()["request_id"] == "rid-10"
    [error] = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert "GET /boom" in error.getMessage() and "RuntimeError: kaputt" in error.getMessage()
    assert error.exc_info is not None
    traceback = logging.Formatter().formatException(error.exc_info)
    assert "ExceptionGroup" not in traceback and traceback.count('raise RuntimeError("kaputt")') == 1
    [access] = access_lines(caplog)
    assert access.fields["status"] == 500  # type: ignore[attr-defined]


def test_a_request_that_makes_something_is_logged_when_it_starts(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A request that ends with its worker - the healthcheck window, the memory - wrote no line at all: the line of a
    request comes when it ends (logging review of 2026-10-08). A POST names its start; a GET, the probes among them,
    does not."""
    with caplog.at_level(logging.INFO, logger="app.api.request_log"):
        client.post("/api/v2/compendium", json={"topic": "Optik", "preset": "llm-free", "parts": ["world"]})
        client.get("/refused")

    lines = [record.getMessage() for record in access_lines(caplog)]
    assert lines[0] == "POST /api/v2/compendium started" and lines[1].startswith("POST /api/v2/compendium 200 ")
    assert [line for line in lines if line.startswith("GET")] == lines[2:]
    assert not any(line.startswith("GET") and line.endswith("started") for line in lines)


def test_the_line_of_an_error_keeps_a_path_with_a_line_break_on_one_line(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The error line named the decoded path, so %0A in a URL broke it and forged a line of the plain format; it is
    quoted as in the line of the request."""
    with caplog.at_level(logging.ERROR):
        client.get("/boom/a%0AERROR%20forged")

    [error] = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert "\n" not in error.getMessage() and "/boom/a%0AERROR%20forged" in error.getMessage()
