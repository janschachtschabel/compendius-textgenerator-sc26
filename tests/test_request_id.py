"""Request ids and error capture (PLAN.md 9, audit OPS-03): every answer and every log line names its request."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.logging import MAX_REQUEST_ID_CHARS, REQUEST_ID_HEADER, current_request_id, set_request_id
from app.main import create_app
from tests.conftest import make_settings


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path_factory.mktemp("rid") / "state")
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
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
    with caplog.at_level(logging.ERROR):
        response = client.get("/boom", headers={REQUEST_ID_HEADER: "rid-7"})
    assert response.status_code == 500
    body = response.json()
    assert body["request_id"] == "rid-7" and "rid-7" in response.headers[REQUEST_ID_HEADER]
    assert "kaputt" not in body["detail"], "the caller learns nothing about the internals"
    assert "rid-7" in caplog.text and "kaputt" in caplog.text


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
