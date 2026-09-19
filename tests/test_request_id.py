"""Request ids and error capture (PLAN.md 9, audit OPS-03): every answer and every log line names its request."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.logging import REQUEST_ID_HEADER, current_request_id
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
