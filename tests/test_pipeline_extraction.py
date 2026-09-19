"""extraction=llm in the pipeline (D33): the model chooses sentences, the blocks keep the sources' wording."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from app.domain.models import SectionStatus
from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.synthesis.citations import collapse
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import EVIDENCE_RE, answer_from_evidence, make_gateway

OFFER_RE = re.compile(r"^(\d+)\.1 (.+)$", re.MULTILINE)
SELECTION_PROMPT = "passage_selection@v1"


def is_selection(body: dict[str, Any]) -> bool:
    return "\nTextstellen:\n" in body["messages"][1]["content"]


def first_sentences(body: dict[str, Any]) -> str:
    """Chooses the first sentence of every offered paragraph; other prompts get the synthesis answer."""
    if not is_selection(body):
        return answer_from_evidence(body)
    return json.dumps({"saetze": [f"{number}.1" for number, _ in OFFER_RE.findall(body["messages"][1]["content"])]})


def _start(text: str) -> str:
    """The beginning of a sentence or list, whether offered (items joined by semicolons) or cited (with bullets)."""
    words = re.sub(r"(^|\s)- ", " ", text).replace("; ", " ").split()
    return " ".join(words)[:80]


def _content(result: Any) -> list[Any]:
    return [s for s in result.sections if s.slot_key not in {"akteure", "quellen", "glossar"}]


@pytest.fixture
def chunks(service: CompendiumService) -> dict[str, str]:
    prepared = service.prepare(GenerateRequest(topic="Optik", parts=["world"]))
    return {chunk.chunk_id: collapse(chunk.text) for chunk in prepared.chunks}


def test_llm_extraction_fills_the_blocks_with_sentences_it_chose_verbatim(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch, chunks: dict[str, str]
) -> None:
    fake = FakeBApi(first_sentences)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(GenerateRequest(topic="Optik", extraction="llm", parts=["world"]))

    assert result.extraction == "llm" and result.generation == "rule-based"
    assert result.frontmatter["extraction"] == "llm" and "extraction_requested" not in result.frontmatter
    assert "Auswahl KI-gestützt" in result.frontmatter["ai_disclosure"]
    assert result.frontmatter["review"]["status"] == "ki-ausgewählt"
    filled = [s for s in _content(result) if s.text]
    assert filled and all(s.status is SectionStatus.LLM_SELECTED for s in filled)
    for section in filled:  # every paragraph is the first sentence of the paragraph it cites
        for paragraph, citation in zip(section.text.split("\n\n"), section.citations, strict=True):
            body = paragraph.rsplit(" [", 1)[0]
            if body.startswith(("- ", "| ")):  # a list or table is taken whole and rendered as such
                continue
            assert body in chunks[citation.chunk_id], (section.slot_id, body)
    assert f"status={SectionStatus.LLM_SELECTED.value}" in result.markdown

    extraction = result.audit.llm["extraction"] if result.audit.llm else {}
    assert extraction["requested"] == extraction["used"] == "llm"
    assert set(extraction["sections"]) >= {s.slot_id for s in filled} and extraction["fallbacks"] == {}
    selection_calls = [b for b in fake.bodies if is_selection(b)]
    assert len(selection_calls) == len(extraction["sections"]) == len(fake.bodies)  # no synthesis call
    tokens = result.audit.llm_tokens
    assert tokens is not None and tokens["calls"] == len(selection_calls)
    assert SELECTION_PROMPT in result.frontmatter["llm"]["prompts"]
    assert result.frontmatter["llm"]["extraction"]["sections"] == extraction["sections"]
    assert "extract" in result.audit.timings_ms


def test_llm_generation_writes_from_the_sentences_the_llm_extraction_chose(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(first_sentences)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(GenerateRequest(topic="Optik", extraction="llm", generation="llm", parts=["world"]))

    assert result.extraction == "llm" and result.generation == "llm"
    assert result.frontmatter["review"]["status"] == "ki-generiert"
    filled = [s for s in _content(result) if s.text]
    assert filled and all(s.status is SectionStatus.LLM for s in filled)
    offers = [b["messages"][1]["content"] for b in fake.bodies if is_selection(b)]
    prompts = [b["messages"][1]["content"] for b in fake.bodies if not is_selection(b)]
    chosen = {_start(text) for offer in offers for _, text in OFFER_RE.findall(offer)}
    evidence = [text for prompt in prompts for *_, text in EVIDENCE_RE.findall(prompt)]
    assert evidence and all(_start(text) in chosen for text in evidence), "the evidence is what the extraction chose"


def test_a_block_where_no_offered_passage_fits_stays_empty(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def nothing_for_the_definition(body: dict[str, Any]) -> str:
        if is_selection(body) and "Baustein: 1 · Themendefinition" in body["messages"][1]["content"]:
            return json.dumps({"saetze": []})
        return first_sentences(body)

    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(nothing_for_the_definition)))
    result = service.generate(GenerateRequest(topic="Optik", extraction="llm", parts=["world"]))
    definition = next(s for s in result.sections if s.slot_id == "sc26_1")
    assert definition.status is SectionStatus.EMPTY and definition.text == ""
    assert result.audit.llm is not None and result.audit.llm["extraction"]["emptied"] == ["sc26_1"]


def test_failing_selection_keeps_the_rule_based_passages(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(first_sentences, statuses=[400] * 40)))
    result = service.generate(GenerateRequest(topic="Optik", extraction="llm", parts=["world"]))
    assert result.extraction == "rule-based" and result.frontmatter["extraction_requested"] == "llm"
    filled = [s for s in _content(result) if s.text]
    assert filled and all(s.status is SectionStatus.EXTRACTIVE for s in filled)
    extraction = result.audit.llm["extraction"] if result.audit.llm else {}
    assert extraction["sections"] == [] and extraction["fallbacks"]
    assert all(reason.startswith("b-api:") for reason in extraction["fallbacks"].values())
    assert "keinen Baustein" in result.audit.llm["note"]  # type: ignore[index]


def test_llm_extraction_without_a_configured_llm_falls_back(service: CompendiumService) -> None:
    assert service.llm is None
    result = service.generate(GenerateRequest(topic="Optik", extraction="llm", parts=["world"]))
    assert result.extraction == "rule-based" and result.frontmatter["extraction_requested"] == "llm"
    assert result.audit.llm is not None and "konfiguriert" in result.audit.llm["note"]


def test_the_default_extraction_comes_from_the_settings(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(first_sentences)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    monkeypatch.setattr(service.settings, "llm_extraction_default", "llm")
    assert service.generate(GenerateRequest(topic="Optik", parts=["world"])).extraction == "llm"
    calls = len(fake.bodies)
    result = service.generate(GenerateRequest(topic="Optik", extraction="rule-based", parts=["world"]))
    assert result.extraction == "rule-based" and result.audit.llm is None and len(fake.bodies) == calls


def test_rule_based_extraction_with_llm_generation_never_asks_for_a_choice(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(first_sentences)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    result = service.generate(GenerateRequest(topic="Optik", generation="llm-fast", parts=["world"]))
    assert result.extraction == "rule-based" and result.generation == "llm-fast"
    assert fake.bodies and not any(is_selection(b) for b in fake.bodies)
    assert result.audit.llm is not None and result.audit.llm["extraction"]["requested"] == "rule-based"
