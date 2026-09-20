"""POST /api/v2/qa (docs/umbau.md U5): pairs for a text or a topic, rule-based or from the LLM.

The rule-based stage needs nothing - no model, no network - and stays the default. The LLM stage falls back
to it rather than failing, and the answer says which one produced the pairs, so nobody has to guess whether
a model was involved.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.service import CompendiumService
from app.settings import Settings
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

TEXT = (
    "Die Optik ist ein Teilgebiet der Physik und handelt vom Licht. "
    "Ein Fernrohr besteht aus einem Objektiv und einem Okular. "
    "Im Jahr 1704 veröffentlichte Newton sein Werk über die Farben des Lichts."
)
PAIRS = "Was ist Licht?;Elektromagnetische Strahlung im sichtbaren Bereich.\nWas ist Optik?;Ein Teilgebiet der Physik."


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def with_llm(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(lambda body: PAIRS)))
    yield client


def test_pairs_from_a_text_need_no_model(client: TestClient) -> None:
    body = client.post("/api/v2/qa", json={"text": TEXT}).json()
    assert body["method"] == "rule-based", "no model is needed to answer"
    assert [pair["question"] for pair in body["pairs"]] == [
        "Was versteht man unter Optik?",
        "Woraus besteht ein Fernrohr?",
        "Was geschah im Jahr 1704?",
    ]
    assert all(pair["answer"] in TEXT for pair in body["pairs"]), "the answer is the sentence, nothing invented"
    assert body["topic"] is None and body["resolution"] is None


def test_the_count_and_the_answer_length_are_respected(client: TestClient) -> None:
    body = client.post("/api/v2/qa", json={"text": TEXT, "count": 2, "max_answer_length": 50}).json()
    assert len(body["pairs"]) == 2
    assert all(len(pair["answer"]) <= 50 for pair in body["pairs"])


def test_pairs_from_a_topic_come_out_of_the_archives(client: TestClient) -> None:
    body = client.post("/api/v2/qa", json={"topic": "Optik"}).json()
    assert body["topic"] == "Optik" and body["resolution"]["title"] == "Optik"
    assert body["chars"] > 0 and body["pairs"], "the archive text has to yield at least one pair"


def test_an_unknown_topic_is_a_404_with_the_resolution(client: TestClient) -> None:
    answer = client.post("/api/v2/qa", json={"topic": "Gibtesnichtimarchiv"})
    assert answer.status_code == 404 and "resolution" in answer.json()["detail"]


def test_the_llm_writes_the_pairs_when_it_is_asked_and_available(with_llm: TestClient) -> None:
    body = with_llm.post("/api/v2/qa", json={"text": TEXT, "method": "llm"}).json()
    assert body["method"] == "llm" and body["note"] is None
    assert [pair["question"] for pair in body["pairs"]] == ["Was ist Licht?", "Was ist Optik?"]


def test_without_a_usable_llm_the_answer_says_it_fell_back(client: TestClient) -> None:
    body = client.post("/api/v2/qa", json={"text": TEXT, "method": "llm"}).json()
    assert body["method"] == "rule-based", "no b-api is configured in the tests"
    assert body["note"] and "LLM" in body["note"]
    assert body["pairs"], "the fallback still delivers"


def test_a_model_answer_that_yields_nothing_falls_back_too(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(lambda body: "ohne Trennzeichen, also kein Paar")))
    body = client.post("/api/v2/qa", json={"text": TEXT, "method": "llm"}).json()
    assert body["method"] == "rule-based" and body["note"]
    assert [pair["question"] for pair in body["pairs"]][:1] == ["Was versteht man unter Optik?"]


def test_either_a_text_or_a_topic_is_required(client: TestClient) -> None:
    assert client.post("/api/v2/qa", json={}).status_code == 422
    assert client.post("/api/v2/qa", json={"text": "x" * 50_001}).status_code == 422
    assert client.post("/api/v2/qa", json={"text": TEXT, "count": 0}).status_code == 422
    assert client.post("/api/v2/qa", json={"text": TEXT, "method": "models"}).status_code == 422


def test_a_text_without_a_single_fitting_sentence_answers_empty_not_error(client: TestClient) -> None:
    body = client.post("/api/v2/qa", json={"text": "Darüber hinaus gibt es weitere Gesichtspunkte zu bedenken."})
    assert body.status_code == 200 and body.json()["pairs"] == []


def test_without_the_tagger_the_answer_says_the_questions_are_unchecked(client: TestClient) -> None:
    """The test service has no spaCy model, so the note has to name the weaker questions (docs/umbau.md U5a)."""
    body = client.post("/api/v2/qa", json={"text": TEXT}).json()
    assert body["note"] and "spaCy" in body["note"]


def test_with_the_tagger_an_adverb_gets_no_question_and_there_is_no_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_qa_pairs import fake_nlp

    monkeypatch.setattr("app.api.v2.qa.load_spacy", lambda model: fake_nlp)
    body = client.post(
        "/api/v2/qa", json={"text": "Daneben sind die nichtlineare Optik und die Quantenoptik von Bedeutung. " + TEXT}
    ).json()
    assert body["note"] is None
    assert "Daneben" not in " ".join(pair["question"] for pair in body["pairs"])
    assert "Was versteht man unter Optik?" in [pair["question"] for pair in body["pairs"]]
