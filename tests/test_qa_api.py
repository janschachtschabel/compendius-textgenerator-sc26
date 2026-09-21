"""POST /api/v2/qa (docs/umbau.md U5): pairs for a text or a topic, rule-based or from the LLM.

The rule-based stage needs nothing - no model, no network - and stays the default. The LLM stage falls back
to it rather than failing, and the answer says which one produced the pairs, so nobody has to guess whether
a model was involved.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.v2.qa import _text_of
from app.domain.models import ArticleSection, Paragraph, Source, SourceRole
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
    assert client.post("/api/v2/qa", json={"text": TEXT, "method": "zauberei"}).status_code == 422


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


def test_the_model_stage_falls_back_when_the_models_are_not_in_the_image(client: TestClient) -> None:
    """docs/umbau.md U5b: the test service carries no weights, so the answer has to say what it did instead."""
    body = client.post("/api/v2/qa", json={"text": TEXT, "method": "models"}).json()
    assert body["method"] == "rule-based"
    assert body["note"] and "Modelle" in body["note"]
    assert body["pairs"], "the fallback still delivers"


def test_the_model_stage_uses_the_two_models_when_they_are_there(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.synthesis.qa_models import Candidate, QaModels

    sentence = "Die Optik ist ein Teilgebiet der Physik."
    candidate = Candidate(text="Die Optik", sentence=sentence, start=0, end=9)
    monkeypatch.setattr("app.api.v2.qa.answer_candidates", lambda doc, text: [candidate])
    monkeypatch.setattr("app.api.v2.qa.load_spacy", lambda model: lambda text: object())
    monkeypatch.setattr(
        "app.api.v2.qa.load_qa_models",
        lambda qg, qa: QaModels(lambda marked: "Was ist die Optik?", lambda q, c: "ein Teilgebiet der Physik"),
    )
    body = client.post("/api/v2/qa", json={"text": TEXT, "method": "models"}).json()
    assert body["method"] == "models" and body["note"] is None
    assert body["pairs"] == [
        {"question": "Was ist die Optik?", "answer": "ein Teilgebiet der Physik", "level": None}
    ], "the model stage has no notion of difficulty, so it assigns no level"


def test_the_model_stage_needs_the_spacy_model_for_its_candidates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.synthesis.qa_models import QaModels

    monkeypatch.setattr("app.api.v2.qa.load_spacy", lambda model: None)
    monkeypatch.setattr("app.api.v2.qa.load_qa_models", lambda qg, qa: QaModels(lambda m: "Frage?", lambda q, c: "A"))
    body = client.post("/api/v2/qa", json={"text": TEXT, "method": "models"}).json()
    assert body["method"] == "rule-based" and body["note"] and "spaCy" in body["note"]


def test_health_says_whether_the_qa_models_are_in_the_image(client: TestClient) -> None:
    """A probe must not pull 1.3 GB into memory, so /health reports presence, not a load."""
    qa_models = client.get("/health").json()["components"]["qa_models"]
    assert qa_models == {"question_generator": "", "answer_model": "", "present": False}


LEVELLED = (
    "Was ist Licht?;Elektromagnetische Strahlung im sichtbaren Bereich.;Primar\n"
    "Was ist Optik?;Ein Teilgebiet der Physik.;Sek I"
)


def test_the_llm_spreads_the_pairs_over_the_levels_it_was_given(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Levels are an option of the llm stage: the prompt names them and every pair carries one."""
    api = FakeBApi(lambda body: LEVELLED)
    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "llm", make_gateway(api))
    body = client.post("/api/v2/qa", json={"text": TEXT, "method": "llm", "levels": ["Primar", "Sek I"]}).json()
    assert body["method"] == "llm"
    assert [pair["level"] for pair in body["pairs"]] == ["Primar", "Sek I"]
    asked = str(api.bodies[0])
    assert "Primar" in asked and "Sek I" in asked, "the prompt has to name the levels it should spread over"


def test_a_level_outside_the_catalogue_is_refused(client: TestClient) -> None:
    """The values come from config/facets.yaml; a made-up one is a bad request, not a silent pass."""
    answer = client.post("/api/v2/qa", json={"text": TEXT, "method": "llm", "levels": ["Klasse 7"]})
    assert answer.status_code == 422
    assert "Klasse 7" in answer.text


def test_levels_without_the_llm_stage_are_said_out_loud(client: TestClient) -> None:
    """Only the llm stage can assign a level; the other two would stamp an empty label."""
    body = client.post("/api/v2/qa", json={"text": TEXT, "method": "rule-based", "levels": ["Primar"]}).json()
    assert body["method"] == "rule-based"
    assert all(pair["level"] is None for pair in body["pairs"])
    assert "Stufen" in (body["note"] or ""), "silently dropping the levels would be the worse failure"


def test_levels_are_also_said_out_loud_when_the_llm_falls_back(client: TestClient) -> None:
    """Asking for llm and getting the templates loses the levels; the note has to name both reasons."""
    body = client.post("/api/v2/qa", json={"text": TEXT, "method": "llm", "levels": ["Primar"]}).json()
    assert body["method"] == "rule-based"
    assert all(pair["level"] is None for pair in body["pairs"])
    note = body["note"] or ""
    assert "LLM nicht konfiguriert" in note, "the reason for the fallback"
    assert "Stufen" in note, "and that the levels went with it"


def test_the_appendix_of_an_article_is_no_source_for_questions(client: TestClient) -> None:
    """Literatur, Weblinks and Einzelnachweise are references, not content - the lexicon says so.

    segment_source has excluded them from the compendium since U1; the QA endpoint read the sections
    directly and did not ask. Measured in the image on 2026-09-21 over four real topics: for a short
    article 21 of 70 sentences were appendix, and at the endpoint's largest count one of a hundred
    candidates came out of one ("2. Auflage" from "2. Auflage.").
    """
    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    source = Source(
        source_id="wikipedia:Probe",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title="Probe",
        url="u",
        sections=[
            ArticleSection(
                heading="",
                path=[],
                level=0,
                paragraphs=[Paragraph(text="Die Optik ist ein Teilgebiet der Physik.")],
            ),
            ArticleSection(
                heading="Literatur",
                path=["Literatur"],
                level=2,
                paragraphs=[Paragraph(text="Barfuß: Populäres Lehrbuch der Optik. 2. Auflage. 1860.")],
            ),
        ],
    )
    text = _text_of([source], service.lexicon)
    assert "Teilgebiet der Physik" in text
    assert "2. Auflage" not in text, "a question about an edition number teaches nobody anything"


def test_levels_may_arrive_in_the_vocabularys_own_wording(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller sends what the Bildungsstufe vocabulary calls it, not what facets.yaml calls it.

    prefLabel, altLabel and the concept URI all name the same level; the endpoint maps them onto the
    project's own value before the prompt sees them, so the model is asked for one vocabulary only.
    """
    api = FakeBApi(lambda body: LEVELLED)
    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "llm", make_gateway(api))
    body = client.post(
        "/api/v2/qa",
        json={
            "text": TEXT,
            "method": "llm",
            "levels": [
                "Primarstufe",
                "http://w3id.org/openeduhub/vocabs/educationalContext/sekundarstufe_1",
            ],
        },
    ).json()
    assert body["method"] == "llm"
    asked = str(api.bodies[0])
    assert "Primar" in asked and "Sek I" in asked
    assert "Primarstufe" not in asked and "sekundarstufe_1" not in asked, "one vocabulary reaches the model"


def test_a_level_without_a_counterpart_names_itself_in_the_refusal(client: TestClient) -> None:
    """Foerderschule and Informelles Lernen are real levels of the vocabulary with no facet value."""
    answer = client.post("/api/v2/qa", json={"text": TEXT, "method": "llm", "levels": ["Förderschule"]})
    assert answer.status_code == 422
    assert "Förderschule" in answer.text
