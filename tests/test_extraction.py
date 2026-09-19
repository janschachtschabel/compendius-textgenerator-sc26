"""Extraction switch (D33): candidates per block and the LLM's choice of sentences over all blocks."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from app.domain.models import Chunk, ChunkKind, ScoredChunk, Source, SourceRole
from app.domain.requests import GenerateRequest
from app.llm.budget import TokenBudget
from app.llm.client import BApiClient
from app.matching.policy import AssignmentResult
from app.service import CompendiumService
from app.synthesis.extraction import ExtractionJob, candidates_for, extract_with_llm
from app.synthesis.extractive import synthesize
from app.synthesis.selection import LlmSelector
from app.templates.manager import TemplateManager
from tests.test_llm_client import BASE, KEY, FakeBApi

TEMPLATE = TemplateManager().get("sc26")
TITLES = {slot.id: slot.title for slot in TEMPLATE.slots}
SOURCE = Source(
    source_id="wikipedia:Optik",
    project="wikipedia",
    role=SourceRole.LEITQUELLE,
    title="Optik",
    url="u",
    is_primary=True,
)
SOURCES = {SOURCE.source_id: SOURCE}


def _chunk(cid: str, heading: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=cid,
        source_id=SOURCE.source_id,
        heading=heading,
        heading_path=[] if heading == "Einleitung" else [heading],
        is_lead=heading == "Einleitung",
        text=text,
    )


CHUNKS = [
    _chunk("c0", "Einleitung", "Die Optik ist das Teilgebiet der Physik, das sich mit dem Licht befasst."),
    _chunk("c1", "Geschichte", "Schon in der Antike untersuchten Gelehrte die Brechung des Lichts."),
    _chunk("c2", "Anwendungen", "Brillen und Mikroskope beruhen auf den Gesetzen der geometrischen Optik."),
    _chunk("c3", "Forschung", "Heute erforscht die Quantenoptik die Wechselwirkung einzelner Photonen."),
]
BY_ID = {chunk.chunk_id: chunk for chunk in CHUNKS}


def _assignment() -> AssignmentResult:
    assigned: dict[str, list[ScoredChunk]] = {slot.id: [] for slot in TEMPLATE.slots}
    assigned["sc26_1"] = [ScoredChunk(chunk=CHUNKS[0], score=2.0, matcher="policy")]
    assigned["sc26_5"] = [ScoredChunk(chunk=CHUNKS[1], score=0.8, matcher="policy")]
    slot_scores = {
        "sc26_1": {"c0": 2.0},
        "sc26_5": {"c1": 0.8, "c3": 0.5, "c2": 0.6},
        "sc26_10": {"c2": 0.7},
    }
    return AssignmentResult(assigned=assigned, unassigned=0, slot_scores=slot_scores)


def _job(fake: FakeBApi, **kwargs: Any) -> ExtractionJob:
    client = BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    return ExtractionJob(selector=LlmSelector(client), budget=budget, topic="Optik", concurrency=2, **kwargs)


def _by_block(answers: dict[str, str]) -> FakeBApi:
    """Answers each selection prompt with the text given for its block title."""

    def responder(body: dict[str, Any]) -> str:
        user = body["messages"][1]["content"]
        block = re.search(r"^Baustein: (.+)$", user, re.MULTILINE)
        assert block is not None
        slot_id = next(sid for sid, title in TITLES.items() if title == block.group(1))
        return answers[slot_id]

    return FakeBApi(responder)


def test_candidates_are_the_rule_based_paragraphs_then_the_next_best_by_the_policy() -> None:
    assignment = _assignment()
    assert [c.chunk.chunk_id for c in candidates_for("sc26_5", assignment, BY_ID, limit=3)] == ["c1", "c2", "c3"]
    assert [c.chunk.chunk_id for c in candidates_for("sc26_5", assignment, BY_ID, limit=2)] == ["c1", "c2"]
    assert [c.chunk.chunk_id for c in candidates_for("sc26_10", assignment, BY_ID, limit=3)] == ["c2"]
    assert candidates_for("sc26_7", assignment, BY_ID, limit=3) == []
    runner_up = candidates_for("sc26_5", assignment, BY_ID, limit=3)[1]
    assert runner_up.score == 0.6 and runner_up.matcher == "policy"


def test_the_rule_based_paragraphs_stay_candidates_beyond_the_limit() -> None:
    assignment = _assignment()
    assignment.assigned["sc26_5"] = [ScoredChunk(chunk=c, score=0.5, matcher="policy") for c in CHUNKS[1:]]
    assert len(candidates_for("sc26_5", assignment, BY_ID, limit=1)) == 3


def test_the_llm_choice_replaces_the_paragraphs_of_each_block_it_answered() -> None:
    fake = _by_block(
        {"sc26_1": json.dumps({"saetze": ["1.1"]}), "sc26_5": "kaputt", "sc26_10": json.dumps({"saetze": []})}
    )
    extracted = extract_with_llm(TEMPLATE, _assignment(), CHUNKS, SOURCES, _job(fake))
    assert [e.chunk.chunk_id for e in extracted.assigned["sc26_1"]] == ["c0"]
    assert extracted.assigned["sc26_1"][0].matcher == "llm"
    assert [e.chunk.chunk_id for e in extracted.assigned["sc26_5"]] == ["c1"]  # unreadable answer: rule-based choice
    assert extracted.assigned["sc26_10"] == []  # no offered paragraph fits
    assert extracted.selected == {"sc26_1", "sc26_10"}
    report = extracted.report
    assert report.slots == ["sc26_1", "sc26_10"] and report.emptied == ["sc26_10"]
    assert list(report.fallbacks) == ["sc26_5"] and "unlesbar" in report.fallbacks["sc26_5"]
    assert report.calls == 3 and report.total_tokens == 3 * 24  # the unreadable answer was paid for as well
    assert report.sentences == 1 and report.prompts == {"passage_selection@v1"} and report.model == "gpt-5.6-luna"
    assert len(fake.bodies) == 3, "blocks without candidates cost no call"


def test_unexpected_errors_keep_the_rule_based_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _job(FakeBApi())

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("kaputt")

    monkeypatch.setattr(job.selector, "select", boom)
    assignment = _assignment()
    extracted = extract_with_llm(TEMPLATE, assignment, CHUNKS, SOURCES, job)
    assert extracted.assigned == assignment.assigned and extracted.selected == set()
    assert set(extracted.report.fallbacks) == {"sc26_1", "sc26_5", "sc26_10"}
    assert all(r == "unerwarteter Fehler (RuntimeError)" for r in extracted.report.fallbacks.values())


def test_the_policy_reports_its_score_of_every_chunk_for_every_block(service: CompendiumService) -> None:
    prepared = service.prepare(GenerateRequest(topic="Optik", parts=["world"]))
    matched = service.match(prepared, None, 12_000)
    scores = matched.assignment.slot_scores
    assert set(scores) == {slot.id for slot in prepared.template.content_slots()}
    lead = next(chunk for chunk in prepared.chunks if chunk.is_lead)
    assert [slot_id for slot_id, by_chunk in scores.items() if lead.chunk_id in by_chunk] == ["sc26_1"]
    assert all(score > 0 for by_chunk in scores.values() for score in by_chunk.values())
    assert sum(len(by_chunk) for by_chunk in scores.values()) > len(prepared.chunks)  # runners-up, not only winners


def test_a_passage_two_blocks_chose_goes_to_the_first_of_them() -> None:
    # The policy gives a paragraph to one block; among the candidates of extraction=llm it can appear in several
    answers = {
        "sc26_1": json.dumps({"saetze": []}),
        "sc26_5": json.dumps({"saetze": ["2.1"]}),  # candidate c2, the runner-up of this block
        "sc26_10": json.dumps({"saetze": ["1.1"]}),  # the same paragraph c2
    }
    extracted = extract_with_llm(TEMPLATE, _assignment(), CHUNKS, SOURCES, _job(_by_block(answers)))
    assert [e.chunk.chunk_id for e in extracted.assigned["sc26_5"]] == ["c2"]
    assert extracted.assigned["sc26_10"] == []  # the sentence is already printed in block 5
    assert extracted.report.deduped == 1 and extracted.report.emptied == ["sc26_1", "sc26_10"]
    assert extracted.report.offered == 5  # 1 + 3 + 1 paragraphs were on offer


def test_a_list_is_printed_once_even_when_two_blocks_take_it() -> None:
    # Lists and tables are one unit, so the sentence fingerprints of the writer do not catch a repeat
    chunk = _chunk("l1", "Teilgebiete", "Geometrische Optik\nWellenoptik")
    listed = [ScoredChunk(chunk=chunk.model_copy(update={"kind": ChunkKind.LIST}), score=0.5)]
    seen: set[str] = set()
    first, citations = synthesize(listed, SOURCES, 0, seen)
    second, more = synthesize(listed, SOURCES, len(citations), seen)
    assert "- Geometrische Optik" in first and citations
    assert second == "" and more == []
