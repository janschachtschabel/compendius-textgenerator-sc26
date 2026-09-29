"""The answers the review page shows, as the endpoints really give them (D66; audit 2026-09-29, U4).

tests/ui/answers/ holds real answers of the five endpoints and the options of the page, made offline from the sample
archives, a curriculum cache of one element, the fixtures of the repository and a b-api that answers every prompt in
its format. Each file is what the page's "Antwort speichern" writes: the request as the page sends it and the answer.
The Node tests render every view of the page with them (tests/ui/answers.test.mjs).

The views read fields the page never checked against an answer: a row read ``audit.node_article.title``, which no
answer has. This test makes the answers anew and compares their form - every field with the kind of what stands there,
not its value - with the files, so a changed answer shows here before the page reads a field that is gone. After a
deliberate change ``UI_ANSWERS=write`` rewrites the files; the Node tests then show whether the page still reads them.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.llm.prompts import get_prompt
from app.main import create_app
from tests.conftest import make_settings
from tests.test_article_choice import rating
from tests.test_lehrplan_api import write_cache
from tests.test_llm_assignment import PARAGRAPH_RE
from tests.test_llm_client import FakeBApi
from tests.test_nodes_api import with_fake_repository
from tests.test_pipeline_llm import answer_from_evidence, make_gateway
from tests.test_wlo_client import MATERIAL, OPTIK

ANSWERS = Path(__file__).parent / "ui" / "answers"
TEXT = "Ernst Abbe entwickelte in Jena das Lichtmikroskop und die Geometrische Optik."
SMALL = {"max_articles": 1, "target_length": 2000}  # a compendium of fewer and shorter blocks, of the same form

# Each answer by the request the page sends for it: from a topic with all three parts and no LLM; from a material, the
# model naming its article and writing blocks (D47, D63); a topic whose curricula hold nothing to check (D58); the
# article of a material beside a topic; a curriculum search with and without elements; entities and pairs of the model
REQUESTS: dict[str, dict[str, Any]] = {
    "compendium_topic": {
        "method": "POST",
        "path": "api/v2/compendium",
        "body": {
            "topic": "Optik",
            "collection_id": OPTIK,
            "parts": ["world", "curricula", "collection"],
            "preset": "llm-free",
            **SMALL,
            "facets_visible": False,
            "empty_slot_policy": "note",
        },
    },
    "compendium_material": {
        "method": "POST",
        "path": "api/v2/compendium",
        "body": {
            "node_id": MATERIAL,
            "parts": ["world", "curricula"],
            "preset": "best-quality-generated",
            **SMALL,
            "facets_visible": False,
            "empty_slot_policy": "omit",
        },
    },
    "compendium_nothing_to_check": {
        "method": "POST",
        "path": "api/v2/compendium",
        "body": {
            "topic": "Photosynthese",
            "parts": ["world", "curricula"],
            "preset": "best-quality",
            "facets_visible": False,
            "empty_slot_policy": "omit",
        },
    },
    "knowledge_material": {
        "method": "POST",
        "path": "api/v2/knowledge",
        "body": {"topic": "Geometrische Optik", "node_id": MATERIAL, "preset": "balanced", "max_chars": 4000},
    },
    "lehrplan_topic": {
        "method": "GET",
        "path": "api/v2/lehrplan/search",
        "query": {"q": "Optik", "mode": "topic", "preset": "best-quality"},
    },
    "lehrplan_nothing_to_check": {
        "method": "GET",
        "path": "api/v2/lehrplan/search",
        "query": {"q": "Bruchrechnung", "mode": "keyword", "preset": "best-quality"},
    },
    "entities_llm": {
        "method": "POST",
        "path": "api/v2/entities",
        "body": {"text": TEXT, "preset": "best-quality", "link": True},
    },
    "qa_llm": {
        "method": "POST",
        "path": "api/v2/qa",
        "body": {"topic": "Optik", "preset": "best-quality", "count": 2, "levels": ["Sek I"]},
    },
}

PROMPTS = {
    get_prompt(name).system: name
    for name in (
        "topic_articles",
        "article_choice",
        "hit_check",
        "paragraph_assignment",
        "section_synthesis",
        "section_enrichment",
        "node_topic",
        "node_topic_with_topic",
        "curriculum_check",
        "entity_extraction",
        "entity_check",
        "qa_pairs",
    )
}


def answering(body: dict[str, Any]) -> str:
    """A b-api that answers every prompt of the service in its format, as the tests of each stage answer it."""
    prompt = PROMPTS.get(body["messages"][0]["content"])
    user = body["messages"][1]["content"]
    if prompt == "topic_articles":
        return json.dumps({"uebersicht": user.splitlines()[0].removeprefix("Thema: "), "artikel": []})
    if prompt == "article_choice":
        return '{"wahl": 1}'
    if prompt == "hit_check":
        return rating({})(body)
    if prompt == "paragraph_assignment":
        return json.dumps(
            {
                alias: ["entwicklung_ausblick" if "Geschichte" in section else "fachinhalte", 0.8]
                for alias, _, _, section in PARAGRAPH_RE.findall(user)
            }
        )
    if prompt in ("section_synthesis", "section_enrichment"):
        return answer_from_evidence(body)
    if prompt == "node_topic":
        return json.dumps({"titel": "Optik"})
    if prompt == "node_topic_with_topic":
        return json.dumps({"titel": user.splitlines()[0].removeprefix("Thema der Lehrkraft: "), "material": "Optik"})
    if prompt in ("curriculum_check", "entity_check"):
        return json.dumps(dict.fromkeys(re.findall(r"^([ea]\d+): ", user, re.MULTILINE), 2))
    if prompt == "entity_extraction":
        named = [("Ernst Abbe", "Ernst Abbe"), ("Jena", ""), ("Lichtmikroskop", "Lichtmikroskop")]
        return json.dumps({"entitaeten": [{"text": text, "titel": title} for text, title in named]}, ensure_ascii=False)
    if prompt == "qa_pairs":
        return "Was untersucht die Optik?;Das Licht und seine Ausbreitung.;Sek I\nWas bricht Licht?;Eine Linse.;Sek I"
    raise AssertionError(f"a prompt this test does not know: {body['messages'][0]['content'][:80]}")


@pytest.fixture(scope="module")
def client(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    state = tmp_path_factory.mktemp("answers") / "state"
    write_cache(state)
    app = with_fake_repository(create_app(make_settings(sample_zims.values(), state, ui_enabled=True)))
    gateway = make_gateway(FakeBApi(answering), per_request=1_000_000)
    app.state.service.llm = gateway
    app.state.llm = gateway  # the options say there is an LLM, as on a server with one
    return TestClient(app)


def ask(client: TestClient, request: dict[str, Any]) -> Any:
    path = f"/{request['path']}"
    response = (
        client.get(path, params=request["query"])
        if request["method"] == "GET"
        else client.post(path, json=request["body"])
    )
    assert response.status_code == 200, response.text[:500]
    return response.json()


def form(value: Any, path: str = "") -> set[str]:
    """Every field of a JSON value with the kind of what stands there - its form, without its values."""
    if isinstance(value, dict):
        return {f"{path}: object"}.union(*(form(item, f"{path}.{key}") for key, item in value.items()))
    if isinstance(value, list):
        return {f"{path}: array"}.union(*(form(item, f"{path}[]") for item in value))
    kind = "null" if value is None else "boolean" if isinstance(value, bool) else type(value).__name__
    return {f"{path}: {kind}"}


def compare(name: str, made: Any) -> None:
    """The form of what the server gives now against the file of that name; ``UI_ANSWERS=write`` renews the file."""
    path = ANSWERS / f"{name}.json"
    if os.environ.get("UI_ANSWERS") == "write":
        ANSWERS.mkdir(exist_ok=True)
        path.write_text(json.dumps(made, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    kept = json.loads(path.read_text(encoding="utf-8"))
    new, gone = sorted(form(made) - form(kept)), sorted(form(kept) - form(made))
    assert not new and not gone, (
        f"The answer of {name} changed its form - new: {new[:12]}, gone: {gone[:12]}. After a deliberate change "
        "UI_ANSWERS=write pytest tests/test_ui_answers.py renews tests/ui/answers/, and node --test tests/ui/ shows "
        "whether the page still reads it."
    )


@pytest.mark.parametrize("name", sorted(REQUESTS))
def test_the_answers_the_page_is_tested_with_have_the_form_the_endpoints_give(client: TestClient, name: str) -> None:
    request = REQUESTS[name]

    compare(name, {"request": request, "answer": ask(client, request)})


def test_the_options_the_page_is_tested_with_have_the_form_the_server_gives(client: TestClient) -> None:
    response = client.get("/ui/options.json")

    assert response.status_code == 200
    compare("options", response.json())


def test_every_file_of_answers_is_one_this_test_makes() -> None:
    assert {path.stem for path in ANSWERS.glob("*.json")} == {*REQUESTS, "options"}
