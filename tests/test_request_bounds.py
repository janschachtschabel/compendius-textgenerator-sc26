"""A request is refused for its shape before its shape costs a worker (audit 2026-09-28, SE-15 and AP-02).

Every unknown field and every wrong element of an unbounded list was a problem of its own, and the 422 returned them
all with the name of each field: 1.3 million unknown fields in 13 MB held a worker for 19 s and 1.9 GB. An archive,
block or level the service does not know came back in full in the error text.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.errors import MAX_PROBLEMS, JsonResponse, validation_error
from app.domain.requests import ARCHIVE_ID_MAX_CHARS, MAX_ARCHIVES
from app.domain.template_bounds import MAX_SLOTS, SLOT_ID_MAX_CHARS
from app.main import create_app
from app.settings import Settings

SMALL = 2_000  # bytes of an answer that repeats nothing of the request
QA_TEXT = "Die Optik ist die Lehre vom Licht und seiner Ausbreitung."
ROUTES = [
    ("/api/v2/compendium", {"topic": "Optik"}),
    ("/api/v2/knowledge", {"topic": "Optik"}),
    ("/api/v2/qa", {"text": QA_TEXT}),
    ("/api/v2/entities", {"text": "Ernst Abbe entwickelte in Jena das Lichtmikroskop."}),
]


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.mark.parametrize(("path", "body"), ROUTES)
def test_many_unknown_fields_are_one_problem_that_names_three(
    client: TestClient, path: str, body: dict[str, Any]
) -> None:
    fields = {f"feld{number}": 1 for number in range(10_000)}

    answer = client.post(path, json={**body, **fields})

    assert answer.status_code == 422
    assert len(answer.content) < SMALL
    [problem] = answer.json()["detail"]
    assert problem["loc"] == ["body"]
    assert problem["msg"] == "Unbekannte Felder: feld0, feld1, feld2 und 9997 weitere"


def test_a_long_unknown_field_name_is_cut_in_the_answer(client: TestClient) -> None:
    answer = client.post("/api/v2/qa", json={"text": QA_TEXT, "x" * 100_000: 1})

    assert answer.status_code == 422
    assert len(answer.content) < SMALL
    [problem] = answer.json()["detail"]
    assert problem["loc"][0] == "body"
    assert problem["loc"][1].startswith("xxx") and problem["loc"][1].endswith("…")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v2/compendium", {"topic": "Optik", "parts": [1] * 10_000}),
        ("/api/v2/compendium", {"topic": "Optik", "existing_markdown": "# Optik", "regenerate_sections": [1] * 10_000}),
        ("/api/v2/entities", {"text": "Ernst Abbe", "methods": [1] * 10_000}),
        ("/api/v2/entities", {"text": "Ernst Abbe", "archives": [1] * 10_000}),
        ("/api/v2/knowledge", {"topic": "Optik", "archives": [1] * 10_000}),
    ],
)
def test_a_list_beyond_its_bound_is_one_problem_whatever_it_holds(
    client: TestClient, path: str, body: dict[str, Any]
) -> None:
    answer = client.post(path, json=body)

    assert answer.status_code == 422
    [problem] = answer.json()["detail"]
    assert problem["type"] == "too_long"


def test_the_bounds_leave_room_for_every_archive_and_block() -> None:
    # The largest ZIM profile subscribes four archives; sc26 has 13 blocks
    assert MAX_ARCHIVES >= 4 and MAX_SLOTS >= 13


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v2/knowledge", {"topic": "Optik", "archives": ["a" * (ARCHIVE_ID_MAX_CHARS + 1)]}),
        ("/api/v2/entities", {"text": "Ernst Abbe", "archives": ["a" * (ARCHIVE_ID_MAX_CHARS + 1)]}),
        (
            "/api/v2/compendium",
            {"topic": "Optik", "existing_markdown": "# Optik", "regenerate_sections": ["a" * (SLOT_ID_MAX_CHARS + 1)]},
        ),
        ("/api/v2/qa", {"text": QA_TEXT, "levels": ["a" * 201]}),
        ("/api/v2/compendium", {"topic": "Optik", "template_id": "a" * 81}),
        ("/api/v2/knowledge", {"topic": "Optik", "template_id": "../sc26"}),
        ("/api/v2/compendium", {"topic": "Optik", "matcher": "m" * 100_000}),
    ],
)
def test_an_identifier_beyond_its_form_is_refused_before_anything_looks_it_up(
    client: TestClient, path: str, body: dict[str, Any]
) -> None:
    answer = client.post(path, json=body)

    assert answer.status_code == 422, answer.text[:300]
    assert len(answer.content) < SMALL
    assert isinstance(answer.json()["detail"], list)  # the validator's problem, not a text that repeats the value


def test_unknown_archives_are_named_three_at_most(client: TestClient) -> None:
    answer = client.post("/api/v2/knowledge", json={"topic": "Optik", "archives": [f"fehlt{n}" for n in range(20)]})

    assert answer.status_code == 404
    assert answer.json()["detail"] == "Unbekannte Archive: fehlt0, fehlt1, fehlt2 und 17 weitere"


def test_unknown_levels_are_named_three_at_most(client: TestClient) -> None:
    answer = client.post("/api/v2/qa", json={"text": QA_TEXT, "levels": [f"Stufe{n}" for n in range(12)]})

    assert answer.status_code == 422
    assert answer.json()["detail"].startswith("Unbekannte Stufen: Stufe0, Stufe1, Stufe2 und 9 weitere. ")


def test_unknown_blocks_are_named_three_at_most(client: TestClient) -> None:
    names = [f"block{n}" for n in range(10)]
    body = {"topic": "Optik", "existing_markdown": "# Optik", "regenerate_sections": names}

    answer = client.post("/api/v2/compendium", json=body)

    assert answer.status_code == 422
    assert "regenerate_sections: block0, block1, block2 und 7 weitere. " in answer.json()["detail"]


def test_a_422_names_twenty_problems_and_counts_the_rest() -> None:
    errors = [
        {"type": "string_type", "loc": ("body", "archives", n), "msg": "Input should be a valid string", "input": n}
        for n in range(1_000)
    ]
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})

    answer = asyncio.run(validation_error(request, RequestValidationError(errors)))

    problems = json.loads(bytes(answer.body))["detail"]
    assert len(problems) == MAX_PROBLEMS + 1
    assert problems[-1] == {
        "type": "too_many_errors",
        "loc": [],
        "msg": f"{1_000 - MAX_PROBLEMS} weitere Fehler nicht aufgeführt",
        "ctx": {"omitted": 1_000 - MAX_PROBLEMS},
    }


def test_an_answer_that_repeats_a_lone_surrogate_is_still_sent() -> None:
    # KO-19: legal in a JSON string, but UTF-8 cannot encode it. No route repeats such a value since SE-15 bounds
    # every identifier (a bounded field refuses the surrogate as string_unicode); the answer class still holds.
    answer = JsonResponse({"detail": "Template nicht gefunden: fehlt" + chr(0xD800)}, status_code=404)

    assert json.loads(bytes(answer.body))["detail"] == "Template nicht gefunden: fehlt" + chr(0xD800)
