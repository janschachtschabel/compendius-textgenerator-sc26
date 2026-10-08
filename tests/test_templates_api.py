"""Template write paths (docs/umbau.md U6): PUT and DELETE behind ADMIN_TOKEN.

The manager could save and delete since the beginning, but nothing could reach it - neither the API nor the
CLI. These tests pin the way in: who may use it, what the built-in templates refuse, and that a written
template is the one the next compendium request gets.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

ADMIN_TOKEN = "s3cret" * 6  # the service refuses a token under 16 characters (audit 2026-09-27, SE-08)
AUTH = {"X-Admin-Token": ADMIN_TOKEN}
TEMPLATE: dict[str, Any] = {
    "id": "mein",
    "name": "Mein Template",
    "slots": [{"id": "a", "slot": "praxis", "title": "Praxis"}],
}


@pytest.fixture
def client(sample_zims: dict[str, Path], tmp_path: Path) -> Iterator[TestClient]:
    settings = make_settings(sample_zims.values(), tmp_path, admin_token=ADMIN_TOKEN)
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


@pytest.mark.parametrize(("pattern", "reason"), [(".*" * 12 + "!", "Schritte"), ("^(a|aa)+$", "Zeichenklasse")])
def test_a_heading_pattern_that_would_hold_a_worker_is_refused_with_its_reason(
    client: TestClient, pattern: str, reason: str
) -> None:
    """A08: the lexicon runs every pattern over every heading; these took seconds on one and were stored."""
    slow = {**TEMPLATE, "slots": [{**TEMPLATE["slots"][0], "heading_patterns": [pattern]}]}
    answer = client.put("/api/v2/templates/mein", json=slow, headers=AUTH)
    assert answer.status_code == 422 and reason in answer.text
    assert client.get("/api/v2/templates/mein").status_code == 404


def test_a_weight_beyond_a_float_is_refused_and_the_stored_template_stays(client: TestClient, tmp_path: Path) -> None:
    """A11: Python reads the JSON number 1e309 as infinity. It was stored as null: PUT answered 200, GET then 404."""
    assert client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH).status_code == 200
    stored = tmp_path / "templates" / "mein.json"
    before = stored.read_bytes()
    body = json.dumps(TEMPLATE).replace('"Praxis"}', '"Praxis", "budget": {"weight": 1e309}}')
    assert "1e309" in body

    answer = client.put("/api/v2/templates/mein", content=body, headers={**AUTH, "Content-Type": "application/json"})

    assert answer.status_code == 422 and "weight" in answer.text
    assert stored.read_bytes() == before
    assert client.get("/api/v2/templates/mein").json()["version"] == 1


def test_a_facet_name_with_markup_is_refused(client: TestClient) -> None:
    """T10: the name stood in the block marker and the visible facet line of every compendium with the template."""
    facets = {"allowed": ["x --><img src=x onerror=alert(1)><!-- y"]}
    marked = {**TEMPLATE, "slots": [{**TEMPLATE["slots"][0], "facets": facets}]}
    answer = client.put("/api/v2/templates/mein", json=marked, headers=AUTH)
    assert answer.status_code == 422 and "facets" in answer.text
    assert client.get("/api/v2/templates/mein").status_code == 404


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({**TEMPLATE, "empty_slot_polcy": "note"}, "empty_slot_polcy"),
        ({**TEMPLATE, "slots": [{**TEMPLATE["slots"][0], "heading_pattern": ["^Praxis$"]}]}, "heading_pattern"),
        ({**TEMPLATE, "slots": [{**TEMPLATE["slots"][0], "budget": {"wieght": 2}}]}, "wieght"),
        ({**TEMPLATE, "slots": [{**TEMPLATE["slots"][0], "facets": {"requried": ["Zeitbezug"]}}]}, "requried"),
    ],
)
def test_a_field_the_schema_does_not_know_is_refused(client: TestClient, body: dict[str, Any], field: str) -> None:
    """S10: "empty_slot_polcy": "note" was dropped without a word, and the template was stored with omit."""
    answer = client.put("/api/v2/templates/mein", json=body, headers=AUTH)
    assert answer.status_code == 422 and field in answer.text
    assert client.get("/api/v2/templates/mein").status_code == 404


def test_many_unknown_fields_of_a_template_are_one_problem_that_names_three(client: TestClient) -> None:
    """As for a request (audit 2026-09-28, SE-15): every unknown field a problem of its own held a worker."""
    fields = {f"feld{number}": 1 for number in range(10_000)}
    answer = client.put("/api/v2/templates/mein", json={**TEMPLATE, **fields}, headers=AUTH)
    assert answer.status_code == 422 and len(answer.content) < 2_000
    assert "feld0, feld1, feld2 und 9997 weitere" in answer.text


def test_a_template_id_is_a_file_name_that_stays_in_its_directory() -> None:
    from pydantic import ValidationError

    from app.templates.schema import Template

    for bad in ("../x", "a/b", "a.b", ""):
        with pytest.raises(ValidationError):
            Template(id=bad, name="x", slots=TEMPLATE["slots"])
    assert Template(id="mein_Template-2", name="x", slots=TEMPLATE["slots"]).id == "mein_Template-2"


@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_an_id_that_is_no_template_id_is_refused_before_it_names_a_file(
    client: TestClient, tmp_path: Path, method: str
) -> None:
    """SE-09: PUT checked the id, GET and DELETE did not. DELETE built STATE_DIR/templates/<id>.json, and on a
    Windows host an id with a backslash reached a JSON file above that directory."""
    victim = tmp_path / "ziel.json"  # one level above tmp_path/templates
    victim.write_text("{}", encoding="utf-8")
    response = client.request(method, "/api/v2/templates/..%5Cziel", headers=AUTH)
    assert response.status_code == 422
    assert victim.exists()


def test_a_write_from_a_version_read_before_another_write_is_refused(client: TestClient) -> None:
    """Audit 2026-10-03, F09: a stale draft overwrote a newer edit. A read names its version as ETag; a write that
    names it in If-Match is refused (412) once another write came between, and the answer names the version now."""
    client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)
    read = client.get("/api/v2/templates/mein")
    assert read.headers["ETag"] == '"1"'

    newer = client.put(
        "/api/v2/templates/mein", json={**TEMPLATE, "name": "Neuer"}, headers={**AUTH, "If-Match": read.headers["ETag"]}
    )
    stale = client.put(
        "/api/v2/templates/mein", json={**TEMPLATE, "name": "Alt"}, headers={**AUTH, "If-Match": read.headers["ETag"]}
    )

    assert newer.status_code == 200 and newer.headers["ETag"] == '"2"'
    assert stale.status_code == 412 and "Version 2" in stale.json()["detail"]
    assert client.get("/api/v2/templates/mein").json()["name"] == "Neuer"


def test_if_match_star_writes_only_over_a_template_there_is(client: TestClient) -> None:
    first = client.put("/api/v2/templates/mein", json=TEMPLATE, headers={**AUTH, "If-Match": "*"})
    client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)
    again = client.put("/api/v2/templates/mein", json=TEMPLATE, headers={**AUTH, "If-Match": "*"})

    assert first.status_code == 412 and again.status_code == 200


@pytest.mark.parametrize(
    ("tags", "status"), [('W/"1"', 412), ("1", 412), ('"eins"', 412), ('"7", "1"', 200), ('"01"', 412)]
)
def test_if_match_compares_strong_tags_only(client: TestClient, tags: str, status: int) -> None:
    """RFC 9110: If-Match takes the strong comparison - a weak tag never matches; a list matches by any of its tags."""
    client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)

    answer = client.put("/api/v2/templates/mein", json=TEMPLATE, headers={**AUTH, "If-Match": tags})

    assert answer.status_code == status


def test_a_template_made_again_after_a_delete_counts_its_version_on(client: TestClient) -> None:
    """The version, which is the ETag, began again after a delete: a draft read before the delete matched the template
    made anew and overwrote it (review of 2026-10-08)."""
    client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)
    read = client.get("/api/v2/templates/mein")
    client.delete("/api/v2/templates/mein", headers=AUTH)

    anew = client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)
    stale = client.put("/api/v2/templates/mein", json=TEMPLATE, headers={**AUTH, "If-Match": read.headers["ETag"]})

    assert anew.headers["ETag"] == '"2"' and stale.status_code == 412


def test_the_version_of_a_new_template_is_the_services(client: TestClient) -> None:
    """A version in the body of a new template was kept: one of 10,000,000,000 had an ETag If-Match never matched."""
    answer = client.put("/api/v2/templates/mein", json={**TEMPLATE, "version": 10_000_000_000}, headers=AUTH)

    assert answer.json()["version"] == 1 and answer.headers["ETag"] == '"1"'


def test_if_match_over_several_header_lines_matches_by_any_of_them(client: TestClient) -> None:
    client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)

    answer = client.put(
        "/api/v2/templates/mein", json=TEMPLATE, headers=[*AUTH.items(), ("If-Match", '"99"'), ("If-Match", '"1"')]
    )

    assert answer.status_code == 200


def test_a_delete_with_if_match_goes_through_only_over_that_version(client: TestClient) -> None:
    """RFC 9110: a server evaluates If-Match before the method, a DELETE too; it deleted a newer edit (review of
    2026-10-08)."""
    client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)
    client.put("/api/v2/templates/mein", json=TEMPLATE, headers=AUTH)  # version 2

    stale = client.delete("/api/v2/templates/mein", headers={**AUTH, "If-Match": '"1"'})
    current = client.delete("/api/v2/templates/mein", headers={**AUTH, "If-Match": '"2"'})

    assert stale.status_code == 412 and "Version 2" in stale.json()["detail"]
    assert current.status_code == 204 and client.get("/api/v2/templates/mein").status_code == 404


def test_the_openapi_document_names_the_etag_of_a_template(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]["/api/v2/templates/{template_id}"]

    assert "ETag" in paths["get"]["responses"]["200"]["headers"]
    assert "ETag" in paths["put"]["responses"]["200"]["headers"]
    assert any(parameter["name"] == "if-match" for parameter in paths["delete"]["parameters"])
