"""LLM generation in the pipeline: LLM sections carry only cited sentences, everything else falls back to rules."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.domain.models import SectionStatus
from app.domain.requests import GenerateRequest
from app.llm.budget import TokenBudget
from app.llm.client import BApiClient, LlmError
from app.llm.gateway import LlmGateway, LlmOptions
from app.llm.prompts import get_prompt
from app.service import CompendiumService
from tests.test_llm_client import BASE, KEY, FakeBApi

EVIDENCE_RE = re.compile(r"^\[(\d+)\] \((.+?) › (.+?)\) (.+)$", re.MULTILINE)
MARKER_RE = re.compile(r"\[(\d+)\]")
SECTION_PROMPT = get_prompt("section_synthesis").tag


def answer_from_evidence(body: dict[str, Any]) -> str:
    """Paraphrases every evidence item with its marker and adds one uncited claim (which must be dropped)."""
    user = body["messages"][1]["content"]
    sentences = [
        f"{text.split('. ')[0].rstrip('.')[:160]} [{number}]." for number, _, _, text in EVIDENCE_RE.findall(user)
    ]
    sentences.append("Dieser Satz behauptet etwas ohne jeden Beleg.")
    return " ".join(sentences)


def make_gateway(fake: FakeBApi, per_request: int = 20_000, **options: Any) -> LlmGateway:
    client = BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))
    settings = {
        "fast_sections": ("sc26_1", "sc26_11"),
        "concurrency": 2,
    }
    settings.update(options)
    return LlmGateway(client, TokenBudget(per_request=per_request, daily=2_000_000), LlmOptions(**settings))


@pytest.fixture
def fake() -> FakeBApi:
    return FakeBApi(answer_from_evidence)


@pytest.fixture
def with_llm(
    service: CompendiumService, fake: FakeBApi, monkeypatch: pytest.MonkeyPatch
) -> Iterator[CompendiumService]:
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    yield service
    monkeypatch.setattr(service, "llm", None)


def _content_sections(result: Any) -> list[Any]:
    return [s for s in result.sections if s.slot_key not in {"akteure", "quellen", "glossar"}]


def test_llm_fast_writes_the_fast_sections_with_cited_sentences_only(
    with_llm: CompendiumService, fake: FakeBApi
) -> None:
    result = with_llm.generate(GenerateRequest(topic="Optik", generation="llm-fast", parts=["world"]))
    assert result.generation == "llm-fast" and result.frontmatter["generation"] == "llm-fast"
    assert "generation_requested" not in result.frontmatter
    by_id = {s.slot_id: s for s in result.sections}
    definition = by_id["sc26_1"]
    assert definition.status is SectionStatus.LLM
    assert definition.llm is not None and definition.llm["prompt"] == SECTION_PROMPT
    assert definition.llm["dropped_sentences"] == 1
    for sentence in re.split(r"(?<=[.!?])\s+", definition.text):
        assert MARKER_RE.search(sentence), sentence
    assert "ohne jeden Beleg" not in definition.text
    used = {int(n) for n in MARKER_RE.findall(definition.text)}
    assert used == {c.number for c in definition.citations}
    llm_sections = [s for s in result.sections if s.status is SectionStatus.LLM]
    assert {s.slot_id for s in llm_sections} <= {"sc26_1", "sc26_11"}
    assert all(
        s.status is SectionStatus.EXTRACTIVE
        for s in _content_sections(result)
        if s.text and s.slot_id not in {"sc26_1", "sc26_11"}
    )

    numbers = [c.number for s in result.sections for c in s.citations]
    assert numbers == list(range(1, len(numbers) + 1)), "citations stay one global sequence"
    assert f"<!-- kompendium:section id=sc26_1 status={SectionStatus.LLM.value}" in result.markdown
    assert (
        "KI-generiert" in result.frontmatter["ai_disclosure"]
        or "Teile KI-generiert" in result.frontmatter["ai_disclosure"]
    )
    llm = result.frontmatter["llm"]
    assert llm["provider"] == "openai" and llm["model"] == "gpt-5.6-luna"
    assert SECTION_PROMPT in llm["prompts"] and "sc26_1" in llm["generation"]["sections"]
    tokens = result.audit.llm_tokens
    assert tokens is not None and tokens["calls"] >= 1 and tokens["total"] == 24 * tokens["calls"]
    assert result.audit.llm is not None and result.audit.llm["generation"]["used"] == "llm-fast"
    assert len(fake.bodies) == len(llm_sections), "one call per block the LLM writes"


def test_llm_generation_writes_every_filled_content_section(with_llm: CompendiumService) -> None:
    result = with_llm.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    filled = [s for s in _content_sections(result) if s.text]
    assert filled and all(s.status is SectionStatus.LLM for s in filled)
    for section in filled:  # text markers and citations agree in every section, not only in the first (offset 0)
        assert {int(n) for n in MARKER_RE.findall(section.text)} == {c.number for c in section.citations}
    numbers = [c.number for s in result.sections for c in s.citations]
    assert numbers == list(range(1, len(numbers) + 1))
    assert result.generation == "llm"
    assert result.audit.llm is not None and result.audit.llm["generation"]["fallbacks"] == {}
    assert "sc26_1" in result.frontmatter["llm"]["generation"]["sections"]
    tokens = result.audit.llm_tokens
    assert tokens is not None and tokens["calls"] >= len(filled)


def test_unreachable_api_at_the_check_falls_back_to_rule_based(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(transport_failures=100)))
    result = service.generate(GenerateRequest(topic="Optik", generation="llm-fast", parts=["world"]))
    assert result.generation == "rule-based" and result.frontmatter["generation"] == "rule-based"
    assert result.frontmatter["generation_requested"] == "llm-fast"
    assert all(s.status is not SectionStatus.LLM for s in result.sections)
    assert result.audit.llm is not None and "erreichbar" in result.audit.llm["note"]
    assert result.audit.llm_tokens is None


def test_failing_calls_fall_back_per_section_and_report_the_generation_actually_used(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(answer_from_evidence, statuses=[400] * 40)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(GenerateRequest(topic="Optik", generation="llm-fast", parts=["world"]))
    assert result.generation == "rule-based" and result.frontmatter["generation_requested"] == "llm-fast"
    assert all(s.status is not SectionStatus.LLM for s in result.sections)
    fallbacks = result.audit.llm["generation"]["fallbacks"] if result.audit.llm else {}
    assert "sc26_1" in fallbacks and "b-api" in fallbacks["sc26_1"]
    assert result.frontmatter["llm"]["generation"]["fallbacks"] == fallbacks


def test_exhausted_budget_falls_back_without_calls(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBApi(answer_from_evidence)
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=100))
    result = service.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    assert result.generation == "rule-based"
    assert result.audit.llm is not None and all(
        "Budget" in reason for reason in result.audit.llm["generation"]["fallbacks"].values()
    )
    assert all(request.url.path.endswith("/models") for request in fake.requests)


def test_llm_request_without_configured_llm_falls_back(service: CompendiumService) -> None:
    assert service.llm is None
    result = service.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    assert result.generation == "rule-based" and result.frontmatter["generation_requested"] == "llm"
    assert result.audit.llm is not None and "konfiguriert" in result.audit.llm["note"]


def test_default_generation_comes_from_the_settings(
    with_llm: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(with_llm.settings, "llm_generation_default", "llm-fast")
    result = with_llm.generate(GenerateRequest(topic="Optik", parts=["world"]))
    assert result.generation == "llm-fast"
    result = with_llm.generate(GenerateRequest(topic="Optik", generation="rule-based", parts=["world"]))
    assert result.generation == "rule-based" and result.audit.llm is None


def test_gateway_status_for_health(fake: FakeBApi) -> None:
    gateway = make_gateway(fake)
    before = gateway.status()
    assert before["available"] is False and before["check"] is None
    assert fake.requests == [], "the health status never calls the b-api itself"
    gateway.check_model()
    status = gateway.status()
    assert status["enabled"] is True and status["available"] is True
    assert status["check"]["ok"] is True and status["model"] == "gpt-5.6-luna"
    assert status["budget"]["daily"] == 2_000_000 and status["budget"]["used_today"] == 0
    assert gateway.generation_slots("llm-fast", {"sc26_1", "sc26_2", "sc26_11"}) == {"sc26_1", "sc26_11"}
    assert gateway.generation_slots("llm", {"sc26_1", "sc26_2"}) == {"sc26_1", "sc26_2"}
    assert gateway.generation_slots("rule-based", {"sc26_1"}) == set()


def test_unexpected_errors_in_the_llm_layer_never_break_the_compendium(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = make_gateway(FakeBApi(answer_from_evidence))

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("kaputt")

    monkeypatch.setattr(gateway.synthesizer, "write_section", boom)
    monkeypatch.setattr(service, "llm", gateway)
    result = service.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    assert result.generation == "rule-based" and result.frontmatter["generation_requested"] == "llm"
    assert result.audit.llm is not None
    fallbacks = result.audit.llm["generation"]["fallbacks"]
    assert fallbacks and all("unerwarteter Fehler (RuntimeError)" in reason for reason in fallbacks.values())
    assert all(s.status is not SectionStatus.LLM for s in result.sections)


def test_target_length_reaches_the_prompt_and_the_output_limit(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def definition_call(target_length: int) -> dict[str, Any]:
        fake = FakeBApi(answer_from_evidence)
        monkeypatch.setattr(service, "llm", make_gateway(fake))
        service.generate(
            GenerateRequest(topic="Optik", generation="llm-fast", parts=["world"], target_length=target_length)
        )
        return next(b for b in fake.bodies if "Baustein: 1 · Themendefinition" in b["messages"][1]["content"])

    short, long = definition_call(2_000), definition_call(60_000)
    target = re.compile(r"Ziellänge: etwa (\d+) Zeichen")
    short_chars = int(target.search(short["messages"][1]["content"]).group(1))  # type: ignore[union-attr]
    long_chars = int(target.search(long["messages"][1]["content"]).group(1))  # type: ignore[union-attr]
    assert short_chars < long_chars
    assert short["max_completion_tokens"] < long["max_completion_tokens"]


def test_malformed_answers_fall_back_per_section(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBApi(raw={"choices": [{"message": "kein Objekt"}], "usage": [1, 2]})
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    assert result.generation == "rule-based" and result.audit.llm is not None
    assert result.audit.llm["generation"]["fallbacks"] and all(
        "Format" in r for r in result.audit.llm["generation"]["fallbacks"].values()
    )


def test_gateway_rechecks_an_unavailable_model_only_after_the_interval() -> None:
    now = [0.0]
    fake = FakeBApi(transport_failures=1)
    client = BApiClient(
        BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake), clock=lambda: now[0]
    )
    gateway = LlmGateway(client, TokenBudget(per_request=20_000, daily=2_000_000), LlmOptions(), clock=lambda: now[0])
    assert gateway.available is False and len(fake.requests) == 1
    now[0] += 300
    assert gateway.available is False and len(fake.requests) == 1, "no second probe within RECHECK_S"
    now[0] += 301
    assert gateway.available is True and len(fake.requests) == 2


def test_gateway_is_unavailable_while_the_client_is_suspended() -> None:
    now = [0.0]
    fake = FakeBApi()
    client = BApiClient(
        BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake), clock=lambda: now[0]
    )
    gateway = LlmGateway(client, TokenBudget(per_request=20_000, daily=2_000_000), LlmOptions(), clock=lambda: now[0])
    assert gateway.available is True
    fake.transport_failures = 3
    with pytest.raises(LlmError):
        client.chat([{"role": "user", "content": "x"}], max_output_tokens=10)
    assert gateway.available is False and "ausgesetzt" in gateway.unavailable_reason
    now[0] += 61
    assert gateway.available is True


def test_budget_running_out_mid_run_with_parallel_drafts(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While one draft holds its reservation the parallel ones are denied; nothing overshoots the request budget."""

    def slow_answer(body: dict[str, Any]) -> str:
        time.sleep(0.3)  # long enough for every other draft to ask for its reservation meanwhile
        return answer_from_evidence(body)

    fake = FakeBApi(slow_answer)
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=3_000, concurrency=4))
    result = service.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    assert result.audit.llm is not None
    written, fallbacks = result.audit.llm["generation"]["sections"], result.audit.llm["generation"]["fallbacks"]
    assert 1 <= len(written) <= 2 and len(fallbacks) >= 3
    assert all("Budget der Anfrage" in reason for reason in fallbacks.values())
    chat_calls = [r for r in fake.requests if r.url.path.endswith("/chat/completions")]
    assert len(chat_calls) == len(written), "a denied draft never reaches the b-api"
    assert result.generation == "llm"


def test_request_timeout_bounds_the_llm_work(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBApi(answer_from_evidence)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    monkeypatch.setattr(service.settings, "request_timeout_s", 5)  # less than the minimum a call needs
    result = service.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    assert result.generation == "rule-based" and result.audit.llm is not None
    fallbacks = result.audit.llm["generation"]["fallbacks"]
    assert fallbacks and all("Zeitbudget" in reason for reason in fallbacks.values())
    assert all(request.url.path.endswith("/models") for request in fake.requests)


def test_mark_mode_shows_conclusions_in_the_document_and_in_the_facets(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(answer_from_evidence), mark_unsupported=True))
    result = service.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    assert result.audit.llm is not None and result.audit.llm["generation"]["marked_sentences"] >= 1
    assert (
        "<!-- f: Evidenzgrad=Schlussfolgerung -->Dieser Satz behauptet etwas ohne jeden Beleg.<!-- /f -->"
        in result.markdown
    )
    llm_sections = [s for s in result.sections if s.status is SectionStatus.LLM]
    assert all(s.llm is not None and s.llm["marked_sentences"] == 1 for s in llm_sections)
    graded = [s for s in llm_sections if "Evidenzgrad" in s.facets]
    assert graded and all("Schlussfolgerung" in s.facets["Evidenzgrad"] for s in graded)
    numbers = [c.number for s in result.sections for c in s.citations]
    assert numbers == list(range(1, len(numbers) + 1))


def answer_with_model_knowledge(body: dict[str, Any]) -> str:
    """Cites every evidence item and adds one sentence the sources do not carry."""
    return f"{answer_from_evidence(body)} Fachleute ordnen das Thema seit Langem der klassischen Physik zu."


def test_enrichment_marks_model_knowledge_in_the_text_and_reports_it(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/umbau.md U4: what the model added beyond the sources is visible, counted and announced."""
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(answer_with_model_knowledge)))
    result = service.generate(
        GenerateRequest(topic="Optik", generation="llm", enrichment="model-knowledge", parts=["world"])
    )
    assert result.enrichment == "model-knowledge"
    assert "<!-- f: Evidenzgrad=Modellwissen -->" in result.markdown
    assert "Evidenzgrad=Schlussfolgerung" not in result.markdown
    llm_sections = [s for s in result.sections if s.status is SectionStatus.LLM]
    assert llm_sections and all(s.llm is not None and s.llm["marked_sentences"] >= 1 for s in llm_sections)
    assert result.audit.llm is not None
    generation = result.audit.llm["generation"]
    assert generation["enrichment"] == "model-knowledge" and generation["marked_sentences"] >= len(llm_sections)
    assert result.frontmatter["enrichment"] == "model-knowledge"
    assert "Modellwissen" in result.frontmatter["ai_disclosure"]
    numbers = [c.number for s in result.sections for c in s.citations]
    assert numbers == list(range(1, len(numbers) + 1)), "the citation sequence stays intact"


def test_the_enrichment_prompt_is_the_one_that_allows_model_knowledge(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(answer_with_model_knowledge)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(
        GenerateRequest(topic="Optik", generation="llm", enrichment="model-knowledge", parts=["world"])
    )
    assert result.frontmatter["llm"]["prompts"] == [get_prompt("section_enrichment").tag]


def test_without_the_switch_nothing_changes(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(answer_with_model_knowledge)))
    result = service.generate(GenerateRequest(topic="Optik", generation="llm", parts=["world"]))
    assert result.enrichment == "sources-only"
    assert "Modellwissen" not in result.markdown
    assert result.frontmatter["llm"]["prompts"] == [SECTION_PROMPT]


def test_enrichment_without_llm_generation_is_reported_as_sources_only(service: CompendiumService) -> None:
    """No LLM writes a block, so nothing can be enriched; the answer must not claim otherwise."""
    result = service.generate(
        GenerateRequest(topic="Optik", generation="rule-based", enrichment="model-knowledge", parts=["world"])
    )
    assert result.enrichment == "sources-only" and "Modellwissen" not in result.markdown


def only_cited_sentences(body: dict[str, Any]) -> str:
    """Stays inside the evidence: the permission to enrich is given, but the model does not use it."""
    user = body["messages"][1]["content"]
    return " ".join(
        f"{text.split('. ')[0].rstrip('.')[:160]} [{number}]." for number, _, _, text in EVIDENCE_RE.findall(user)
    )


def test_the_disclosure_claims_model_knowledge_only_when_there_is_some(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mode says what was allowed; the AI disclosure has to say what the text actually contains (Art. 50)."""
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(only_cited_sentences)))
    result = service.generate(
        GenerateRequest(topic="Optik", generation="llm", enrichment="model-knowledge", parts=["world"])
    )
    assert result.enrichment == "model-knowledge", "the switch was honoured"
    assert result.audit.llm is not None and result.audit.llm["generation"]["marked_sentences"] == 0
    assert "Modellwissen" not in result.frontmatter["ai_disclosure"]
    assert "Modellwissen" not in result.markdown
