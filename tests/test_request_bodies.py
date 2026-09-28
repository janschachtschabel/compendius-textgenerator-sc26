"""Request bodies a caller controls: their size is bounded before anything reads them, and an error answer neither
repeats them nor fails on what they hold (audit 2026-09-27, SE-02 and KO-19)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.body_limit import MAX_BODY_BYTES, BodySizeLimit
from app.api.v2.qa_schemas import MAX_TEXT_CHARS
from app.main import create_app
from app.settings import Settings

# A JSON escape for half a surrogate pair: legal in a JSON string, but no character UTF-8 can encode. Spelled with
# chr(92) so that no tool on the way turns the backslash into something else.
LONE_SURROGATE = chr(92) + "ud800"
JSON = {"content-type": "application/json"}


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def small_app(max_bytes: int) -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(payload: dict[str, str]) -> dict[str, int]:
        return {"characters": sum(len(value) for value in payload.values())}

    app.add_middleware(BodySizeLimit, max_bytes=max_bytes)
    return app


def chunks(total: int) -> Iterator[bytes]:
    """A JSON object of ``total`` bytes, sent without a Content-Length (chunked)."""
    yield b'{"a": "'
    remaining = total - len(b'{"a": ""}')
    while remaining > 0:
        piece = min(remaining, 16)
        yield b"x" * piece
        remaining -= piece
    yield b'"}'


def test_a_body_over_the_limit_is_refused_with_413(client: TestClient) -> None:
    response = client.post("/api/v2/compendium", content=b" " * (MAX_BODY_BYTES + 1), headers=JSON)

    assert response.status_code == 413
    assert str(MAX_BODY_BYTES) in response.json()["detail"]
    assert response.headers["x-request-id"]  # the refusal is a request of the service like any other
    assert response.headers["connection"] == "close"  # the unread body must not be taken for the next request


def test_the_limit_leaves_room_for_the_largest_field_escaped_throughout() -> None:
    # existing_markdown takes 2,000,000 characters, and a client may spell each as a six-byte escape
    assert MAX_BODY_BYTES >= 6 * 2_000_000


def test_a_chunked_body_is_counted_while_it_arrives() -> None:
    client = TestClient(small_app(max_bytes=64))

    refused = client.post("/echo", content=chunks(65), headers=JSON)
    passed = client.post("/echo", content=chunks(64), headers=JSON)

    assert refused.status_code == 413
    assert passed.status_code == 200
    assert passed.json() == {"characters": 64 - len(b'{"a": ""}')}


def test_a_declared_length_over_the_limit_is_refused_without_reading() -> None:
    client = TestClient(small_app(max_bytes=64))

    response = client.post("/echo", content=b'{"a": "' + b"x" * 100 + b'"}', headers=JSON)

    assert response.status_code == 413


def test_a_validation_error_does_not_repeat_the_input(client: TestClient) -> None:
    response = client.post("/api/v2/qa", json={"text": "x" * (MAX_TEXT_CHARS + 1)})

    assert response.status_code == 422
    assert len(response.content) < 2_000  # FastAPI's own answer carried the 50,001 characters back
    errors = response.json()["detail"]
    assert errors
    assert errors[0]["loc"] == ["body", "text"]
    assert all("input" not in error for error in errors)


def test_a_lone_surrogate_in_an_invalid_request_is_a_422(client: TestClient) -> None:
    # pydantic refuses the surrogate in a field it measures; the 422 used to repeat it and then fail to encode
    body = '{"topic": "Optik' + LONE_SURROGATE + '", "preset": "gibt-es-nicht"}'

    response = client.post("/api/v2/compendium", content=body.encode(), headers=JSON)

    assert response.status_code == 422
    failed = {tuple(error["loc"]): error["type"] for error in response.json()["detail"]}
    assert failed == {("body", "topic"): "string_unicode", ("body", "preset"): "literal_error"}


def test_a_lone_surrogate_in_a_template_id_is_refused_not_repeated(client: TestClient) -> None:
    # The 404 named the template the caller asked for, surrogate included, and failed to encode. Since SE-15 the id
    # has the pattern of the path; the answer class that still encodes such a text: tests/test_request_bounds.py
    body = '{"topic": "Optik", "template_id": "fehlt' + LONE_SURROGATE + '"}'

    response = client.post("/api/v2/compendium", content=body.encode(), headers=JSON)

    assert response.status_code == 422
    assert [error["loc"] for error in json.loads(response.content)["detail"]] == [["body", "template_id"]]
