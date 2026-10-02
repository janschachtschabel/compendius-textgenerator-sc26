"""D72 (Jan, 2026-10-02): every prompt hears the topic as asked, the enrichment profile fills empty blocks, and a
writing profile words the topic of a text.

- "das thema im prompt sollte bei best-quality generated auch das angefragte thema und nicht der gefundene artikel sein -
  das sollte eigentlich für alle profile gelten. eine verfälschung des themas ist generell nicht gut."
- "bei best quality generated sollten auch leere bausteine aus modellwissen geschrieben werden - genau so war es mal
  gedacht gewesen - ki sollte ergänzen und texte glätten."
- "wenn das thema zu lang ist oder eine texteingabe war sollte in den beiden profilen die ki das thema passend zum input
  formulieren"; a node can stand in for the topic or come with it.

The searches in the archives and the curricula keep the article; a text the rules print keeps it as its heading.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

import app.service as service_module
from app.domain.models import SectionStatus
from app.domain.requests import GenerateRequest
from app.knowledge.article_choice import ArticleChoiceJob
from app.knowledge.node_article import NodeArticleReport
from app.knowledge.topic_wording import METADATA, SENTENCE
from app.llm.call import LlmSkipped
from app.llm.prompts import get_prompt
from app.service import CompendiumService
from app.settings import Settings
from app.sources.wlo.models import NodeInfo
from app.synthesis.llm import LlmSection, LlmSynthesizer
from app.templates.manager import TemplateManager
from tests.test_lehrplan_api import write_cache
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import answer_with_model_knowledge, make_gateway

ASKED = "Optik in Klasse 7"
WORDING = get_prompt("topic_wording").system
ASSIGNMENT = get_prompt("paragraph_assignment").system
CURRICULUM = get_prompt("curriculum_check").system


def users(fake: FakeBApi, system: str) -> list[str]:
    """The user messages of the calls whose system message starts with ``system``."""
    return [body["messages"][1]["content"] for body in fake.bodies if body["messages"][0]["content"].startswith(system)]


def wording_then(answer: Any, topic: str) -> FakeBApi:
    """The model words ``topic`` and answers every other call with ``answer``."""
    return FakeBApi(
        lambda body: json.dumps({"thema": topic}) if body["messages"][0]["content"] == WORDING else answer(body)
    )


def test_the_enrichment_profile_writes_every_block_about_the_topic_as_asked(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(answer_with_model_knowledge)
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    result = service.generate(
        GenerateRequest(topic=ASKED, generation="llm", enrichment="model-knowledge", parts=["world"])
    )

    assert (result.topic, result.resolution.title) == (ASKED, "Optik")
    content = {slot.id for slot in TemplateManager().get("sc26").content_slots()}
    assert {s.slot_id for s in result.sections if s.status is SectionStatus.LLM} == content
    assert all(user.startswith(f"Thema: {ASKED}\n") for user in users(fake, "Du formulierst einen Baustein"))
    assert result.frontmatter["llm"]["prompts"] == [get_prompt("section_enrichment").tag]


def test_a_block_without_evidence_is_written_from_the_models_knowledge() -> None:
    fake = FakeBApi(lambda body: "Licht breitet sich geradlinig aus [1]. Spiegel werfen es zurück.")
    gateway = make_gateway(fake)
    slot = TemplateManager().get("sc26").content_slots()[0]

    section = LlmSynthesizer(gateway.client).write_section(
        slot, [], {}, topic="Optik", citation_start=0, budget=gateway.open_budget(), enrich=True
    )

    assert isinstance(section, LlmSection)
    assert section.citations == [] and section.marked_sentences == 2
    assert "Belege:\n(keine)" in fake.bodies[0]["messages"][1]["content"]


def test_without_enrichment_a_block_without_evidence_stays_with_the_rules() -> None:
    fake = FakeBApi(lambda body: "Licht breitet sich geradlinig aus.")
    gateway = make_gateway(fake)
    slot = TemplateManager().get("sc26").content_slots()[0]

    section = LlmSynthesizer(gateway.client).write_section(
        slot, [], {}, topic="Optik", citation_start=0, budget=gateway.open_budget()
    )

    assert isinstance(section, LlmSkipped) and fake.bodies == []


def test_the_matching_hears_the_topic_as_asked_and_the_rules_text_keeps_its_article(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(lambda body: "{}")
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    result = service.generate(GenerateRequest(topic=ASKED, matcher="llm", parts=["world"]))

    assert users(fake, ASSIGNMENT) and all(
        user.startswith(f"Thema des Kompendiums: {ASKED}\n") for user in users(fake, ASSIGNMENT)
    )
    assert result.topic == "Optik", "a text the rules printed is about its article"


def test_the_hit_check_hears_the_topic_as_asked(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    heard: list[str] = []

    def hits(job: ArticleChoiceJob, topic: str, sources: Any) -> Any:
        heard.append(topic)
        return set(), None

    monkeypatch.setattr(service_module, "check_hits", hits)
    gateway = make_gateway(FakeBApi())
    request = GenerateRequest(topic=ASKED, parts=["world"])

    prepared = service.prepare(request, choice=ArticleChoiceJob(gateway.client, gateway.open_budget()))

    assert prepared.side_articles > 0 and heard == [ASKED]


def test_the_curriculum_check_hears_the_topic_as_asked(
    service: CompendiumService, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_cache(settings.state_dir)
    fake = FakeBApi(lambda body: json.dumps({"e1": 2}))
    monkeypatch.setattr(service, "llm", make_gateway(fake))

    service.generate(
        GenerateRequest(
            topic=ASKED, parts=["world", "curricula"], subject="Physik", preset="llm-free", curriculum_check="llm"
        )
    )

    heard = users(fake, CURRICULUM)
    assert heard and all(user.startswith(f"Thema des Kompendiums: {ASKED} (Fach: Physik)\n") for user in heard)


def test_a_writing_profile_words_a_question_in_place_of_a_topic(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = wording_then(answer_with_model_knowledge, "Grundlagen der Optik")
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    result = service.generate(
        GenerateRequest(topic="Was ist Optik?", generation="llm", enrichment="model-knowledge", parts=["world"])
    )

    assert result.topic == "Grundlagen der Optik"
    assert users(fake, WORDING) == ["Anfrage der Lehrkraft: Was ist Optik?\n\nGib das JSON-Objekt zurück."]
    assert all(
        user.startswith("Thema: Grundlagen der Optik\n") for user in users(fake, "Du formulierst einen Baustein")
    )
    audit = result.audit.llm
    assert audit is not None and audit["topic_wording"] == {
        "source": "Thema",
        "reason": SENTENCE,
        "topic": "Grundlagen der Optik",
        "fallback": None,
    }
    assert get_prompt("topic_wording").tag in result.frontmatter["llm"]["prompts"]
    assert result.frontmatter["llm"]["topic_wording"]["topic"] == "Grundlagen der Optik"


def test_without_a_wording_the_question_stays_the_topic(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(
        lambda body: "kein JSON" if body["messages"][0]["content"] == WORDING else answer_with_model_knowledge(body)
    )
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    result = service.generate(
        GenerateRequest(topic="Was ist Optik?", generation="llm", enrichment="model-knowledge", parts=["world"])
    )

    assert result.topic == "Was ist Optik?"
    assert result.audit.llm is not None and result.audit.llm["topic_wording"]["fallback"]


def test_without_part_1_a_writing_profile_words_no_topic(
    service: CompendiumService, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_cache(settings.state_dir)
    fake = wording_then(lambda body: json.dumps({"e1": 2}), "Grundlagen der Optik")
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    service.generate(
        GenerateRequest(
            topic="Was ist Optik?", subject="Physik", generation="llm", curriculum_check="llm", parts=["curricula"]
        )
    )

    assert users(fake, WORDING) == []
    assert users(fake, CURRICULUM) and all(
        user.startswith("Thema des Kompendiums: Was ist Optik?") for user in users(fake, CURRICULUM)
    )


def test_a_profile_that_writes_nothing_asks_for_no_wording(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(lambda body: "{}")
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    result = service.generate(GenerateRequest(topic="Was ist Optik?", matcher="llm", parts=["world"]))

    assert users(fake, WORDING) == []
    assert result.audit.llm is not None and result.audit.llm["topic_wording"] is None
    assert all(user.startswith("Thema des Kompendiums: Was ist Optik?\n") for user in users(fake, ASSIGNMENT))


def material(title: str = "Stationsarbeit zur Optik") -> NodeInfo:
    return NodeInfo(
        node_id="5f2e1a3b-0000-4000-8000-000000000001",
        kind="material",
        title=title,
        description="Acht Stationen zu Spiegelung und Brechung des Lichts.",
        keywords=("Licht",),
        subject_uris=(),
        subject_labels=("Physik",),
        educational_contexts=(),
        url="",
    )


def test_a_material_without_a_topic_is_worded_from_its_metadata_in_a_writing_profile(
    service: CompendiumService,
) -> None:
    prepared = replace(
        service.prepare(GenerateRequest(topic="Optik", parts=["world"])), node_article=NodeArticleReport()
    )
    fake = FakeBApi(lambda body: json.dumps({"thema": "Spiegelung und Brechung des Lichts"}))
    gateway = make_gateway(fake)
    request = GenerateRequest(node_id=material().node_id, parts=["world"])

    service._ask_topic(prepared, request, material(), None)
    assert prepared.prompt_topic == "Optik", "without a writing profile a material's topic is its article (D47)"

    service._ask_topic(prepared, request, material(), ArticleChoiceJob(gateway.client, gateway.open_budget()))
    assert prepared.prompt_topic == "Spiegelung und Brechung des Lichts"
    assert prepared.wording is not None and (prepared.wording.source, prepared.wording.reason) == ("Material", METADATA)
    assert users(fake, WORDING)[0].startswith("Titel des Materials: Stationsarbeit zur Optik\nFächer: Physik\n")


def test_a_short_topic_sent_with_a_node_leads_without_a_wording(service: CompendiumService) -> None:
    prepared = service.prepare(GenerateRequest(topic=ASKED, parts=["world"]))
    fake = FakeBApi(lambda body: json.dumps({"thema": "Anderes Thema"}))
    gateway = make_gateway(fake)

    service._ask_topic(
        prepared,
        GenerateRequest(topic=ASKED, node_id=material().node_id, parts=["world"]),
        material(),
        ArticleChoiceJob(gateway.client, gateway.open_budget()),
    )

    assert prepared.prompt_topic == ASKED and prepared.wording is None and fake.bodies == []
