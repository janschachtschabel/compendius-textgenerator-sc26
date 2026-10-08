"""Whatever the model answers to every question, each endpoint ends in its documented fallbacks, never in a 500.

tests/test_llm_answers.py takes the readers one by one (audit 2026-09-27, KO-03). Here every question of a request gets
the same broken answer, in every profile that asks the model and at every endpoint that does (Jan, 2026-10-08: "fälle
einplanen bei denen eine llm rückmeldung fehlschlägt oder nicht sauber geparst werden kann").
"""

from __future__ import annotations

import json
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

from app.domain.requests import Preset
from app.main import create_app
from app.service import CompendiumService
from app.settings import Settings
from tests.test_lehrplan_api import write_cache
from tests.test_llm_client import FakeBApi
from tests.test_llm_synthesis import cut_off
from tests.test_pipeline_llm import make_gateway

BROKEN = {
    "empty": "",
    "prose": "Dazu kann ich leider nichts sagen.",
    "empty object": "{}",
    "list": "[1, 2, 3]",
    "null": "null",
    "cut off": '{"p1": ["fachinhalte", 0.9], "p2": ["defin',
    "wrong types": json.dumps(
        {"uebersicht": 5, "artikel": "Optik", "wahl": [1], "p1": {"x": 1}, "e1": "passt", "titel": None, "text": 7}
    ),
    "unknown keys": json.dumps({"p999": ["erfunden", 1.0], "e999": 2, "zzz": "?"}),
}
LLM_PROFILES = [preset for preset in get_args(Preset) if preset != "llm-free"]
TEXT = "Die Optik ist ein Teilgebiet der Physik und handelt vom Licht. Ein Fernrohr besteht aus Objektiv und Okular."


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    write_cache(settings.state_dir)  # part 2 and the curriculum search read their elements from it
    return TestClient(create_app(settings), raise_server_exceptions=False)


def answering(client: TestClient, monkeypatch: pytest.MonkeyPatch, answer: str) -> FakeBApi:
    """The model of the client's service answers ``answer`` to every question."""
    fake = FakeBApi(lambda body: answer)
    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=400_000))
    return fake


def asked(fake: FakeBApi) -> int:
    """The questions the model got, the list of models aside."""
    return len(fake.bodies)


REASONS = ("fallback", "fallbacks", "articles_fallback", "hits_fallback")  # where a step of audit.llm names one


@pytest.mark.parametrize("preset", LLM_PROFILES)
@pytest.mark.parametrize(("kind", "answer"), BROKEN.items(), ids=BROKEN.keys())
def test_a_compendium_falls_back_whatever_the_model_answers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, preset: str, kind: str, answer: str
) -> None:
    fake = answering(client, monkeypatch, answer)

    reply = client.post(
        "/api/v2/compendium",
        json={"topic": "Optik", "parts": ["world", "curricula"], "subject": "Physik", "preset": preset},
    )

    assert reply.status_code == 200, reply.text
    assert asked(fake) > 0, "the profile asked the model nothing: the test proves nothing"
    body = reply.json()
    assert set(body["parts_status"]) == {"world", "curricula"}
    steps = [step for step in body["audit"]["llm"].values() if isinstance(step, dict)]
    assert any(step.get(field) for step in steps for field in REASONS), "no step named its fallback"
    if kind != "prose":  # a refusal in prose is text to the writer: the service does not recognise one (D93)
        assert not body["audit"]["llm"]["generation"]["sections"], "a broken answer stood in the text as a block"


ENDPOINTS = {
    "qa text": ("post", "/api/v2/qa", {"text": TEXT}),
    "qa topic": ("post", "/api/v2/qa", {"topic": "Optik"}),
    "entities": ("post", "/api/v2/entities", {"text": TEXT}),
    "knowledge": ("post", "/api/v2/knowledge", {"topic": "Optik"}),
    "lehrplan": ("get", "/api/v2/lehrplan/search", {"q": "Optik", "mode": "topic"}),
}
ASKING = [  # the profiles that ask the model there: balanced makes its pairs with the rules (D57)
    pytest.param(name, preset, id=f"{name}-{preset}")
    for name in ENDPOINTS
    for preset in LLM_PROFILES
    if not (name.startswith("qa") and preset == "balanced")
]


def fell_back(endpoint: str, body: dict[str, Any]) -> bool:
    """Whether the answer of ``endpoint`` names the fallback where that endpoint reports it."""
    if endpoint.startswith("qa"):
        return bool(body["method"] == "rule-based")
    if endpoint == "entities":
        return bool(body["llm"]["fallback"])
    choice = body["article_choice"] if endpoint == "knowledge" else body["llm"]["article_choice"]
    check = {} if endpoint == "knowledge" else body["llm"]["curriculum_check"] or {}
    return any(step.get(field) for step in (choice, check) for field in REASONS)


@pytest.mark.parametrize("answer", BROKEN.values(), ids=BROKEN.keys())
@pytest.mark.parametrize(("endpoint", "preset"), ASKING)
def test_every_other_endpoint_falls_back_whatever_the_model_answers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, answer: str, endpoint: str, preset: str
) -> None:
    fake = answering(client, monkeypatch, answer)
    method, path, fields = ENDPOINTS[endpoint]
    sent = {**fields, "preset": preset}

    reply = client.get(path, params=sent) if method == "get" else client.post(path, json=sent)

    assert reply.status_code == 200, reply.text
    assert asked(fake) > 0, "the profile asked the model nothing: the test proves nothing"
    assert fell_back(endpoint, reply.json()), "the answer named no fallback"


def test_a_compendium_names_the_blocks_the_output_limit_cut(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A block whose answer broke off keeps its finished sentences, and the audit names the blocks that lost one."""
    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    fake = FakeBApi(raw=cut_off("Die Optik ist die Lehre vom Licht [1]. Linsen brechen es an ihren"))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=400_000))

    body = client.post(
        "/api/v2/compendium", json={"topic": "Optik", "parts": ["world"], "preset": "best-quality-generated"}
    ).json()

    generation = body["audit"]["llm"]["generation"]
    assert generation["cut_off"] and set(generation["cut_off"]) <= set(generation["sections"])
    assert "Lehre vom Licht" in body["markdown"] and "Linsen brechen es an ihren" not in body["markdown"]
