"""Template write paths (docs/umbau.md U6): PUT and DELETE behind ADMIN_TOKEN.

The manager could save and delete since the beginning, but nothing could reach it - neither the API nor the
CLI. These tests pin the way in: who may use it, what the built-in templates refuse, and that a written
template is the one the next compendium request gets.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

AUTH = {"X-Admin-Token": "s3cret"}
TEMPLATE = {
    "id": "mein",
    "name": "Mein Template",
    "slots": [{"id": "a", "slot": "praxis", "title": "Praxis"}],
}


@pytest.fixture
def client(sample_zims: dict[str, Path], tmp_path: Path) -> Iterator[TestClient]:
    settings = make_settings(sample_zims.values(), tmp_path, admin_token="s3cret")
    with TestClient(create_app(settings)) as started:
        yield started


@pytest.fixture
def without_token(sample_zims: dict[str, Path], tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(sample_zims.values(), tmp_path))) as started:
        yield started


def test_a_template_can_be_written_read_back_and_deleted(client: TestClient) -> None:
    written = client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)
    assert written.status_code == 200
    assert written.json()["version"] == 1 and written.json()["builtin"] is False
    assert client.get("/api/v2/templates/mein").json()["name"] == "Mein Template"
    assert "mein" in {t["id"] for t in client.get("/api/v2/templates").json()}

    assert client.delete("/api/v2/templates/mein", headers=AUTH).status_code == 204
    assert client.get("/api/v2/templates/mein").status_code == 404


def test_writing_again_counts_the_version_up(client: TestClient) -> None:
    assert client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH).json()["version"] == 1
    assert client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH).json()["version"] == 2


def test_a_builtin_template_is_read_only(client: TestClient) -> None:
    written = client.put("/api/v2/templates/sc26", json={**TEMPLATE, "id": "sc26"}, headers=AUTH)
    assert written.status_code == 409 and "sc26" in written.json()["detail"]
    deleted = client.delete("/api/v2/templates/sc26", headers=AUTH)
    assert deleted.status_code == 409
    assert client.get("/api/v2/templates/sc26").json()["slots"], "the built-in template is untouched"


def test_the_id_in_the_path_and_in_the_body_have_to_agree(client: TestClient) -> None:
    answer = client.put("/api/v2/templates/anders", json=TEMPLATE, headers=AUTH)
    assert answer.status_code == 422 and "mein" in answer.json()["detail"]


def test_an_invalid_template_is_refused(client: TestClient) -> None:
    assert (
        client.put("/api/v2/templates/leer", json={"id": "leer", "name": "x", "slots": []}, headers=AUTH).status_code
        == 422
    )


def test_deleting_something_that_is_not_there_is_a_404(client: TestClient) -> None:
    assert client.delete("/api/v2/templates/gibtesnicht", headers=AUTH).status_code == 404


def test_without_the_token_nothing_can_be_written(client: TestClient) -> None:
    assert client.put("/api/v2/templates/mein", json=TEMPLATE).status_code == 403
    assert client.delete("/api/v2/templates/mein", headers={"X-Admin-Token": "falsch"}).status_code == 403
    assert client.get("/api/v2/templates").status_code == 200, "reading stays open"


def test_without_a_configured_token_the_write_paths_do_not_exist(without_token: TestClient) -> None:
    assert without_token.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH).status_code == 404


def test_a_heading_pattern_that_is_no_regular_expression_is_refused(client: TestClient) -> None:
    """It used to be stored, and every compendium with the template answered 500 when the lexicon compiled it."""
    broken = {**TEMPLATE, "slots": [{**TEMPLATE["slots"][0], "heading_patterns": ["Praxis", "("]}]}
    answer = client.put("/api/v2/templates/mein", json=broken, headers=AUTH)
    assert answer.status_code == 422 and "heading_patterns" in answer.text


def test_a_template_id_is_a_file_name_that_stays_in_its_directory() -> None:
    from pydantic import ValidationError

    from app.templates.schema import Template

    for bad in ("../x", "a/b", "a.b", ""):
        with pytest.raises(ValidationError):
            Template(id=bad, name="x", slots=TEMPLATE["slots"])
    assert Template(id="mein_Template-2", name="x", slots=TEMPLATE["slots"]).id == "mein_Template-2"
