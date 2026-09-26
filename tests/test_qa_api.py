"""POST /api/v2/qa (docs/umbau.md U5): pairs for a text or a topic, rule-based or from the LLM.

The rule-based stage needs nothing - no model, no network - and stays the default. The LLM stage falls back
to it rather than failing, and the answer says which one produced the pairs, so nobody has to guess whether
a model was involved.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.models import AuditReport, Compendium, Resolution, Section, SectionStatus
from app.llm.budget import RequestBudget
from app.llm.call import TIME_UP
from app.llm.deadline import Deadline
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
    body = with_llm.post("/api/v2/qa", json={"text": TEXT, "method": "llm", "count": 2}).json()
    assert body["method"] == "llm" and body["note"] is None
    assert [pair["question"] for pair in body["pairs"]] == ["Was ist Licht?", "Was ist Optik?"]


def test_the_llm_method_without_a_configured_llm_is_a_503(client: TestClient) -> None:
    """D53: no b-api is configured in the tests; asking for it is refused instead of answered by the templates."""
    for asked in ({"method": "llm"}, {"preset": "best-quality"}, {"preset": "best-quality-generated"}):
        answer = client.post("/api/v2/qa", json={"text": TEXT, **asked})
        assert answer.status_code == 503 and "method=llm" in answer.json()["detail"], asked


def test_the_profile_picks_the_method_and_a_method_the_request_sets_wins(client: TestClient) -> None:
    """D57: llm-free and balanced take the rules, the LLM profiles the b-api; a method the request sets wins."""
    assert client.post("/api/v2/qa", json={"text": TEXT, "preset": "llm-free"}).json()["method"] == "rule-based"
    assert client.post("/api/v2/qa", json={"text": TEXT}).json()["method"] == "rule-based", "the tests' profile"
    chosen = client.post("/api/v2/qa", json={"text": TEXT, "preset": "best-quality", "method": "rule-based"})
    assert chosen.status_code == 200 and chosen.json()["method"] == "rule-based", "the method needs no LLM"


def test_balanced_asks_with_the_rules_as_llm_free_does(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """D57 (Jan): the default profile asks fast and without extra resources - with the same rules as llm-free."""
    from tests.recorded_spacy import RecordedNlp

    monkeypatch.setattr("app.api.v2.qa.load_spacy", lambda model: RecordedNlp())
    text = "Ein Vulkan ist eine geologische Struktur. Einstein wurde 1879 in Ulm geboren."
    answers = [
        client.post("/api/v2/qa", json={"text": text, "preset": preset, "count": 2})
        for preset in ("balanced", "llm-free")
    ]
    assert [answer.status_code for answer in answers] == [200, 200], "a text needs no LLM in balanced"
    balanced, free = (answer.json() for answer in answers)
    assert balanced["method"] == "rule-based" and balanced["note"] is None
    assert balanced["pairs"] == free["pairs"]


def test_the_stages_no_profile_uses_are_gone(client: TestClient) -> None:
    """D57: models and parse-based were removed; asking for one is a 422, not a quiet fallback to the rules."""
    for method in ("models", "parse-based"):
        answer = client.post("/api/v2/qa", json={"text": TEXT, "method": method})
        assert answer.status_code == 422, method


def test_fewer_pairs_than_asked_for_are_named_in_the_note(client: TestClient) -> None:
    """Jan, 2026-09-25: 20 asked, about 5 delivered and not a word about it. The count is an upper bound."""
    body = client.post("/api/v2/qa", json={"text": TEXT, "count": 20}).json()
    assert len(body["pairs"]) == 3 and "3 statt 20 Paare" in body["note"]
    assert "das LLM (llm) fragt freier" in body["note"] and "Modelle" not in body["note"], "D57: no models any more"


def test_an_llm_profile_lets_the_llm_write_the_pairs(with_llm: TestClient) -> None:
    body = with_llm.post("/api/v2/qa", json={"text": TEXT, "preset": "best-quality"}).json()
    assert body["method"] == "llm" and [pair["question"] for pair in body["pairs"]] == [
        "Was ist Licht?",
        "Was ist Optik?",
    ]


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


def test_with_the_parse_the_rules_ask_varied_questions_and_there_is_no_note(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D55: with the spaCy model the rule stage asks from the parse (app/synthesis/qa_rules.py), not the templates."""
    from tests.recorded_spacy import RecordedNlp

    monkeypatch.setattr("app.api.v2.qa.load_spacy", lambda model: RecordedNlp())
    text = "Ein Vulkan ist eine geologische Struktur. Einstein wurde 1879 in Ulm geboren."
    body = client.post("/api/v2/qa", json={"text": text, "method": "rule-based", "count": 2}).json()
    assert body["method"] == "rule-based" and body["note"] is None
    assert [pair["question"] for pair in body["pairs"]] == [
        "Was ist ein Vulkan?",
        "Wann wurde Einstein in Ulm geboren?",
    ]


def test_health_reports_no_qa_models_any_more(client: TestClient) -> None:
    """D57: the two QA models left the image, and their component left /health with them."""
    assert "qa_models" not in client.get("/health").json()["components"]


def test_a_leftover_model_path_is_named_at_start(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """D57: the settings are gone, and a stale value in an environment would otherwise change nothing without a word."""
    from app.main import warn_about_removed_settings

    monkeypatch.setenv("QG_MODEL_PATH", "/models/qg")
    monkeypatch.setenv("QA_MODEL_PATH", "/models/qa")
    with caplog.at_level("WARNING"):
        warn_about_removed_settings()
    assert "QG_MODEL_PATH, QA_MODEL_PATH" in caplog.text and "D57" in caplog.text


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


def test_levels_are_also_said_out_loud_when_the_llm_falls_back(
    with_llm: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking for llm and getting the templates loses the levels; the note has to name both reasons."""
    monkeypatch.setattr(
        with_llm.app.state.service,
        "llm_unavailable",
        lambda: "LLM nicht verfügbar (b-api antwortet nicht); Regelmodus verwendet",
    )  # type: ignore[attr-defined]
    body = with_llm.post("/api/v2/qa", json={"text": TEXT, "method": "llm", "levels": ["Primar"]}).json()
    assert body["method"] == "rule-based"
    assert all(pair["level"] is None for pair in body["pairs"])
    note = body["note"] or ""
    assert "LLM nicht verfügbar" in note, "the reason for the fallback"
    assert "Stufen" in note, "and that the levels went with it"


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


def test_a_topic_asks_the_compendium_it_makes_first(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pipeline is: make the compendium, then ask about it — not: ask the raw articles.

    With a topic the endpoint used to read the whole corpus. Measured at the running service on
    2026-09-21 that was 50 068 characters against 31 050 in the compendium, and the pairs showed it:
    "Was geschah im Jahr 1240?" came out of the history deep in an article, which the compendium does
    not carry. Only the blocks are asked about, not the markdown around them — a question about a
    citation number or a heading teaches nobody anything.
    """
    block = "Die Brechzahl von Wasser beträgt etwa 1,33 und bestimmt den Winkel des gebrochenen Strahls."
    asked: dict[str, Any] = {}

    def only_part_one(payload: Any, **_: Any) -> Compendium:  # deadline and budget, as CompendiumService.generate
        asked["parts"] = list(payload.parts)
        asked["topic"] = payload.topic
        return Compendium(
            topic="Optik",
            resolution=Resolution(query="Optik", normalized="Optik", title="Optik"),
            template_id="sc26",
            template_version=1,
            extraction="rule-based",
            generation="rule-based",
            generated_at="2026-09-21T00:00:00Z",
            audit=AuditReport(),
            sections=[Section(slot_id="s1", slot_key="themendefinition", title="Definition", text=block)],
        )

    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "generate", only_part_one)
    body = client.post("/api/v2/qa", json={"topic": "Optik"}).json()
    assert asked == {"parts": ["world"], "topic": "Optik"}, "part 1 is the text; parts 2 and 3 are listings"
    assert body["chars"] == len(block), "the pairs are made from the block, nothing else"
    assert body["topic"] == "Optik" and body["resolution"]["title"] == "Optik"
    assert all(pair["answer"] in block for pair in body["pairs"])


def _optik(*sections: Section) -> Compendium:
    return Compendium(
        topic="Optik",
        resolution=Resolution(query="Optik", normalized="Optik", title="Optik"),
        template_id="sc26",
        template_version=1,
        extraction="rule-based",
        generation="rule-based",
        generated_at="2026-09-25T00:00:00Z",
        audit=AuditReport(),
        sections=list(sections),
    )


BLOCK = Section(
    slot_id="s1",
    slot_key="themendefinition",
    title="Definition",
    text="Die Brechzahl von Wasser beträgt etwa 1,33 und bestimmt den Winkel des gebrochenen Strahls.",
)


def test_part_one_is_made_without_an_llm_whatever_the_profile(
    with_llm: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D55 (Jan): the pairs are asked of the compendium the LLM-free procedure makes; the profile picks only the
    method of the pairs. An article choice the request names still goes along, as every single switch does."""
    asked: list[tuple[str | None, str | None]] = []

    def capture(payload: Any, **_: Any) -> Compendium:
        asked.append((payload.preset, payload.article_choice))
        return _optik(BLOCK)

    service: CompendiumService = with_llm.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "generate", capture)
    assert with_llm.post("/api/v2/qa", json={"topic": "Optik", "preset": "best-quality"}).json()["method"] == "llm"
    with_llm.post("/api/v2/qa", json={"topic": "Optik", "preset": "balanced", "article_choice": "llm"})
    assert asked == [("llm-free", "rule-based"), ("llm-free", "llm")], "the rules choose unless the request says"


def test_the_rule_stage_hears_the_glossary_the_actors_and_the_topic(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D55: the glossary and the actor list are generated blocks, no prose to parse, but their definitions and
    first sentences make questions of their own; the rules read them from the blocks, not from the text."""
    from tests.recorded_spacy import RecordedNlp

    heard: dict[str, Any] = {}

    def spy(text: str, **kwargs: Any) -> list[Any]:
        heard.update(text=text, **kwargs)
        return []

    glossary = Section(
        slot_id="s2", slot_key="glossar", title="Glossar", text="GLOSSAR", status=SectionStatus.GENERATED
    )
    actors = Section(slot_id="s3", slot_key="akteure", title="Akteure", text="AKTEURE", status=SectionStatus.GENERATED)
    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "generate", lambda payload, **_: _optik(BLOCK, glossary, actors))
    monkeypatch.setattr("app.api.v2.qa.load_spacy", lambda model: RecordedNlp())
    monkeypatch.setattr("app.api.v2.qa.rule_pairs", spy)
    client.post("/api/v2/qa", json={"topic": "Optik", "method": "rule-based"})
    assert heard["text"] == BLOCK.text, "the generated blocks stay out of the prose"
    assert (heard["glossary"], heard["actors"], heard["topic"]) == ("GLOSSAR", "AKTEURE", "Optik")


def test_a_text_is_still_taken_as_it_comes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller who already has the compendium hands its markdown over; nothing is generated."""

    def never(payload: Any) -> Compendium:
        raise AssertionError("a text needs no compendium")

    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "generate", never)
    body = client.post("/api/v2/qa", json={"text": TEXT}).json()
    assert body["chars"] == len(TEXT) and body["topic"] is None


def test_the_generated_blocks_are_no_source_for_questions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sources, glossary and the actor directory are apparatus, not subject matter.

    Measured against the running service on 2026-09-21 for one topic: of 27 614 characters of blocks,
    20 522 were the three generated ones - link lists, a markdown glossary table and the sources block
    with its ISBN-laden literature lines. Asked about, they yield "Was geschah im Jahr 1999?" answered
    with "Pabst, Lengerich 1999, ISBN 3-934252-13-3", which is where the flood of year questions came
    from. Three quarters of the text taught nothing.
    """
    content = "Die Brechzahl von Wasser beträgt etwa 1,33 und bestimmt den Winkel des gebrochenen Strahls."
    apparatus = "Ludwig Bergmann, Clemens Schaefer: Optik. De Gruyter, Berlin 2004, ISBN 3-11-017081-7."

    def with_apparatus(payload: Any, **_: Any) -> Compendium:
        return Compendium(
            topic="Optik",
            resolution=Resolution(query="Optik", normalized="Optik", title="Optik"),
            template_id="sc26",
            template_version=1,
            extraction="rule-based",
            generation="rule-based",
            generated_at="2026-09-21T00:00:00Z",
            audit=AuditReport(),
            sections=[
                Section(slot_id="s1", slot_key="fachinhalte", title="Fachinhalte", text=content),
                Section(
                    slot_id="s2",
                    slot_key="quellen",
                    title="Quellen",
                    text=apparatus,
                    status=SectionStatus.GENERATED,
                ),
            ],
        )

    service: CompendiumService = client.app.state.service  # type: ignore[attr-defined]
    monkeypatch.setattr(service, "generate", with_apparatus)
    body = client.post("/api/v2/qa", json={"topic": "Optik", "count": 10}).json()
    assert body["chars"] == len(content), "only the subject matter is asked about"
    assert all("ISBN" not in pair["answer"] for pair in body["pairs"])


def _node_app(settings: Settings, monkeypatch: pytest.MonkeyPatch, answer: str) -> tuple[TestClient, FakeBApi]:
    from app.main import create_app as build
    from tests.test_nodes_api import with_fake_repository

    app = with_fake_repository(build(settings))
    api = FakeBApi(lambda body: answer)
    monkeypatch.setattr(app.state.service, "llm", make_gateway(api, per_request=100_000))
    return TestClient(app), api


def test_the_llm_stage_takes_the_levels_and_the_keywords_of_a_node(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D47: a node's levels become the levels of the pairs, its title and keywords their focus."""
    from tests.test_wlo_client import MATERIAL

    client, api = _node_app(settings, monkeypatch, "Was ist die Netzhaut?;Die Schicht im Auge.;Sek I")
    body = client.post("/api/v2/qa", json={"node_id": MATERIAL, "method": "llm"}).json()
    assert body["method"] == "llm" and body["pairs"][0]["level"] == "Sek I"
    asked = api.bodies[-1]["messages"][1]["content"]
    assert "Stufen (Bildungsstufe): Sek I." in asked
    assert "„Stationsarbeit zur Optik“ mit den Schlagwörtern Auge, Netzhaut, Pupille, Linse, Lochkamera" in asked
    assert "Stufen aus dem Knoten: Sek I" in (body["note"] or "")


def test_levels_sent_along_win_over_those_of_the_node(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_wlo_client import MATERIAL

    client, api = _node_app(settings, monkeypatch, "Was ist Licht?;Strahlung.;Primar")
    body = client.post("/api/v2/qa", json={"node_id": MATERIAL, "method": "llm", "levels": ["Primar"]}).json()
    assert "Stufen (Bildungsstufe): Primar." in api.bodies[-1]["messages"][1]["content"]
    assert "Stufen aus dem Knoten" not in (body["note"] or "")


def test_other_stages_take_no_levels_from_a_node_and_say_nothing_about_them(client: TestClient) -> None:
    from tests.test_nodes_api import with_fake_repository
    from tests.test_wlo_client import MATERIAL

    app = with_fake_repository(create_app(client.app.state.settings))  # type: ignore[attr-defined]
    body = TestClient(app).post("/api/v2/qa", json={"node_id": MATERIAL, "method": "rule-based"}).json()
    assert body["method"] == "rule-based" and "Stufen" not in (body["note"] or "")


def test_qa_chooses_the_article_as_the_compendium_does(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """article_choice, preset and subject reach the part 1 the pairs are made from (review of 2026-09-25)."""
    from tests.test_wlo_client import EXAM

    client, api = _node_app(settings, monkeypatch, '{"titel": "Optik"}')
    for switch in ({"article_choice": "llm"}, {"preset": "balanced"}):
        body = client.post("/api/v2/qa", json={"node_id": EXAM, **switch}).json()
        assert body["topic"] == "Optik", switch
    assert any("Unterrichtsmaterial" in call["messages"][0]["content"] for call in api.bodies)
    assert client.post("/api/v2/qa", json={"node_id": EXAM}).status_code == 404, "the rules alone find none"
    subject = client.post("/api/v2/qa", json={"topic": "Brechung", "subject": "Physik"}).json()
    assert subject["resolution"]["confident"], "the subject decides the meaning, as in a compendium"


def test_a_text_of_blanks_is_no_text(client: TestClient) -> None:
    """It used to pass and come back as a 404 about the archives (review of 2026-09-25)."""
    answer = client.post("/api/v2/qa", json={"text": "  \n\t "})
    assert answer.status_code == 422 and "text" in answer.text


def test_a_text_goes_alone_or_the_topic_would_replace_it_unsaid(client: TestClient) -> None:
    """With a topic or a node, part 1 was made and the text dropped without a word (review of 2026-09-25)."""
    from tests.test_wlo_client import EXAM

    for other in ({"topic": "Optik"}, {"node_id": EXAM}):
        answer = client.post("/api/v2/qa", json={"text": TEXT, **other})
        assert answer.status_code == 422 and "nicht beides" in answer.text, other


def test_the_switches_of_part_1_need_a_topic_or_a_node(client: TestClient) -> None:
    """subject and article_choice decide the article of part 1; a text alone has none to decide. preset goes with a
    text as well, since it picks the method of the pairs (D53)."""
    for switch in ({"subject": "Physik"}, {"article_choice": "llm"}):
        answer = client.post("/api/v2/qa", json={"text": TEXT, **switch})
        assert answer.status_code == 422 and next(iter(switch)) in answer.text, switch


def test_part_1_and_the_pairs_spend_one_budget(with_llm: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The llm stage opened a second token budget and deadline after part 1 (review of 2026-09-25)."""
    gateway = with_llm.app.state.service.llm  # type: ignore[attr-defined]
    opened: list[RequestBudget] = []
    real = gateway.open_budget
    monkeypatch.setattr(gateway, "open_budget", lambda: opened.append(real()) or opened[-1])
    body = with_llm.post("/api/v2/qa", json={"topic": "Optik", "method": "llm", "article_choice": "llm"}).json()
    assert body["method"] == "llm", body["note"]
    assert len(opened) == 1, "part 1 and the pairs share one budget"


def test_the_note_says_why_the_llm_call_did_not_happen(with_llm: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A spent budget used to read as an answer without pairs."""
    gateway = with_llm.app.state.service.llm  # type: ignore[attr-defined]
    monkeypatch.setattr(gateway, "open_budget", lambda: RequestBudget(gateway.budget, 10))
    body = with_llm.post("/api/v2/qa", json={"text": TEXT, "method": "llm"}).json()
    assert body["method"] == "rule-based" and "Token-Budget der Anfrage" in body["note"], body["note"]


def test_part_1_and_the_pairs_share_one_deadline(with_llm: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The llm stage opened a deadline of its own after part 1; the time part 1 spent is now gone for the pairs."""
    monkeypatch.setattr("app.api.v2.qa.Deadline", lambda seconds: Deadline(0))  # the request's time, all spent
    body = with_llm.post("/api/v2/qa", json={"topic": "Optik", "method": "llm"}).json()
    assert body["method"] == "rule-based" and TIME_UP in body["note"], body["note"]


def test_an_unavailable_llm_is_named_once(with_llm: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The note read 'LLM nicht verfügbar: LLM nicht verfügbar (...); Regelmodus verwendet; Regelmodus verwendet'."""
    reason = "LLM nicht verfügbar (b-api antwortet nicht); Regelmodus verwendet"
    monkeypatch.setattr(with_llm.app.state.service, "llm_unavailable", lambda: reason)  # type: ignore[attr-defined]
    body = with_llm.post("/api/v2/qa", json={"text": TEXT, "method": "llm"}).json()
    assert body["note"].startswith(reason) and body["note"].count("Regelmodus verwendet") == 1, body["note"]


def test_an_llm_is_asked_for_only_where_the_pairs_or_the_article_of_a_node_need_one(
    client: TestClient, settings: Settings
) -> None:
    """D55: a topic's part 1 needs no LLM, so balanced asks the small models without one and best-quality needs it
    only for the pairs. A material node needs it for its article in every LLM profile, as a compendium does (D47):
    the rules find the article of a material in about half of the cases."""
    from app.main import create_app as build
    from tests.test_nodes_api import with_fake_repository
    from tests.test_wlo_client import EXAM

    assert client.post("/api/v2/qa", json={"topic": "Optik", "preset": "balanced"}).status_code == 200
    refused = client.post("/api/v2/qa", json={"topic": "Optik", "preset": "best-quality"}).json()["detail"]
    assert "method=llm" in refused and "article_choice" not in refused
    node = TestClient(with_fake_repository(build(settings)))
    refused = node.post("/api/v2/qa", json={"node_id": EXAM, "preset": "balanced"})
    assert refused.status_code == 503
    assert "article_choice=llm" in refused.json()["detail"] and "Profil balanced" in refused.json()["detail"]
