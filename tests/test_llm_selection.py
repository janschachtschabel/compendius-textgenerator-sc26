"""LLM passage selection (D33): the model names sentence numbers, the text stays the source's wording."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.domain.models import Chunk, ChunkKind, ScoredChunk, Source, SourceRole
from app.llm.budget import TokenBudget
from app.llm.call import LlmSkipped
from app.llm.client import BApiClient
from app.llm.prompts import get_prompt
from app.synthesis.extractive import usable_sentences
from app.synthesis.selection import (
    MAX_CANDIDATE_CHARS,
    LlmSelector,
    Selection,
    candidate_block,
    numbered_sentences,
    parse_selection,
)
from app.templates.manager import TemplateManager
from app.templates.schema import TemplateSlot
from tests.test_llm_client import BASE, KEY, FakeBApi

SOURCE = Source(
    source_id="wikipedia:Optik",
    project="wikipedia",
    role=SourceRole.LEITQUELLE,
    title="Optik",
    url="u",
    is_primary=True,
)
SOURCES = {SOURCE.source_id: SOURCE}
LEAD = (
    "Die Optik ist das Teilgebiet der Physik, das sich mit dem Licht befasst. "
    "Sie beschreibt die Ausbreitung des Lichts in Medien. "
    "Kurz."
)
HISTORY = (
    "Schon in der Antike untersuchten Gelehrte die Brechung des Lichts. "
    "Im 17. Jahrhundert entstanden die ersten leistungsfähigen Fernrohre."
)
PARTS = "Geometrische Optik\nWellenoptik\nQuantenoptik"


def _chunk(cid: str, heading: str, text: str, kind: ChunkKind = ChunkKind.TEXT) -> Chunk:
    return Chunk(
        chunk_id=cid,
        source_id=SOURCE.source_id,
        heading=heading,
        heading_path=[] if heading == "Einleitung" else [heading],
        heading_level=0 if heading == "Einleitung" else 2,
        is_lead=heading == "Einleitung",
        kind=kind,
        text=text,
    )


CANDIDATES = [
    ScoredChunk(chunk=_chunk("c0", "Einleitung", LEAD), score=2.0, matcher="policy"),
    ScoredChunk(chunk=_chunk("c1", "Geschichte", HISTORY), score=0.7, matcher="policy"),
    ScoredChunk(chunk=_chunk("c2", "Teilgebiete", PARTS, ChunkKind.LIST), score=0.5, matcher="policy"),
]


def _client(fake: FakeBApi) -> BApiClient:
    return BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))


def _slot(target_chars: int = 1200) -> TemplateSlot:
    slot = TemplateManager().get("sc26").slots[0]
    return slot.model_copy(update={"budget": slot.budget.model_copy(update={"target_chars": target_chars})})


def _answer(*ids: str) -> FakeBApi:
    return FakeBApi(lambda body: json.dumps({"saetze": list(ids)}))


def _select(fake: FakeBApi, candidates: list[ScoredChunk] = CANDIDATES, **kwargs: Any) -> Selection | LlmSkipped:
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    slot = kwargs.pop("slot", _slot())
    return LlmSelector(_client(fake)).select(slot, candidates, SOURCES, topic="Optik", budget=budget, **kwargs)


def test_sentences_offered_are_the_usable_ones_of_the_extractive_rules() -> None:
    assert numbered_sentences(CANDIDATES[0].chunk) == usable_sentences(LEAD)
    assert "Kurz." not in numbered_sentences(CANDIDATES[0].chunk)  # too short to stand alone


def test_a_long_paragraph_is_offered_up_to_the_character_cap() -> None:
    sentence = "Dieser Satz über die Brechung des Lichts an Grenzflächen ist ziemlich lang. "
    text = sentence * 40
    offered = numbered_sentences(_chunk("c9", "Brechung", text))
    assert 1 <= len(offered) < 40
    assert sum(len(s) + 1 for s in offered) <= MAX_CANDIDATE_CHARS + len(sentence)


def test_a_list_is_one_unit() -> None:
    assert numbered_sentences(CANDIDATES[2].chunk) == ["Geometrische Optik; Wellenoptik; Quantenoptik"]


def test_the_offer_numbers_paragraphs_and_their_sentences() -> None:
    block, ids = candidate_block(CANDIDATES, SOURCES)
    lines = block.splitlines()
    assert lines[0] == "[1] (Optik › Einleitung)"
    assert lines[1] == "1.1 Die Optik ist das Teilgebiet der Physik, das sich mit dem Licht befasst."
    assert "[2] (Optik › Geschichte)" in lines and "[3] (Optik › Teilgebiete; Liste)" in lines
    assert ids["2.2"] == (1, 1) and ids["3.1"] == (2, 0) and "1.3" not in ids


def test_parse_selection_reads_the_json_answer() -> None:
    assert parse_selection('{"saetze": ["1.1", "2.3"]}') == ["1.1", "2.3"]
    assert parse_selection('Hier: {"saetze": [" [1.2] ", 7, "x"]} fertig') == ["1.2", "7", "x"]
    assert parse_selection('{"saetze": []}') == []
    assert parse_selection("Ich wähle Satz 1.1") is None
    assert parse_selection('{"begruendung": "keine"}') is None


def test_numbers_in_the_answer_keep_their_digits() -> None:
    # A model may answer with JSON numbers instead of strings; 2.10 must not become 2.1
    assert parse_selection('{"saetze": [1.1, 2.10, 3]}') == ["1.1", "2.10", "3"]


def test_an_answer_without_a_single_offered_number_keeps_the_rule_based_paragraphs() -> None:
    result = _select(FakeBApi(lambda body: '{"saetze": ["12.1", "nein"]}'))
    assert isinstance(result, LlmSkipped) and "unlesbar" in result.reason and result.calls == 1


def test_select_returns_the_chosen_sentences_verbatim_in_the_models_paragraph_order() -> None:
    fake = _answer("2.2", "1.2", "1.1", "9.9")
    result = _select(fake)
    assert isinstance(result, Selection)
    assert [e.chunk.chunk_id for e in result.excerpts] == ["c1", "c0"]  # first mention decides the order
    assert result.excerpts[0].chunk.text == "Im 17. Jahrhundert entstanden die ersten leistungsfähigen Fernrohre."
    assert result.excerpts[1].chunk.text == (  # source order inside a paragraph
        "Die Optik ist das Teilgebiet der Physik, das sich mit dem Licht befasst. "
        "Sie beschreibt die Ausbreitung des Lichts in Medien."
    )
    assert result.sentences == 3 and result.invalid == 1 and result.offered == 3
    assert result.excerpts[0].matcher == "llm" and result.excerpts[0].score == 0.7
    assert result.prompt == get_prompt("passage_selection").tag and result.model == "gpt-5.6-luna"
    assert result.total_tokens == 24 and result.cut == 0


def test_a_chosen_list_keeps_its_whole_text_and_kind() -> None:
    result = _select(_answer("3.1"))
    assert isinstance(result, Selection)
    assert result.excerpts[0].chunk.text == PARTS and result.excerpts[0].chunk.kind is ChunkKind.LIST


def test_an_empty_choice_means_no_passage_fits() -> None:
    result = _select(_answer())
    assert isinstance(result, Selection) and result.excerpts == [] and result.sentences == 0


def test_an_unreadable_answer_falls_back_with_the_cost_of_the_call() -> None:
    result = _select(FakeBApi(lambda body: "Die Sätze 1.1 und 2.1 passen."))
    assert isinstance(result, LlmSkipped) and "unlesbar" in result.reason
    assert result.calls == 1 and result.total_tokens == 24


def test_an_exhausted_budget_makes_no_call() -> None:
    fake = _answer("1.1")
    budget = TokenBudget(per_request=50, daily=2_000_000).open_request()
    result = LlmSelector(_client(fake)).select(_slot(), CANDIDATES, SOURCES, topic="Optik", budget=budget)
    assert isinstance(result, LlmSkipped) and "Budget" in result.reason and fake.requests == []


def test_no_candidates_make_no_call() -> None:
    fake = _answer("1.1")
    result = _select(fake, candidates=[])
    assert isinstance(result, LlmSkipped) and fake.requests == []


def test_the_prompt_carries_the_block_and_the_numbered_offer() -> None:
    fake = _answer("1.1")
    _select(fake)
    system, user = (m["content"] for m in fake.bodies[0]["messages"])
    assert "Nummern" in system and '{"saetze"' in system
    assert "Thema: Optik" in user and "Themendefinition" in user and "Ziellänge: etwa 1200 Zeichen" in user
    assert "1.1 Die Optik ist das Teilgebiet der Physik" in user


def test_a_choice_far_beyond_the_target_length_is_cut_by_paragraphs() -> None:
    result = _select(_answer("1.1", "1.2", "2.1", "2.2"), slot=_slot(target_chars=60))
    assert isinstance(result, Selection)
    assert [e.chunk.chunk_id for e in result.excerpts] == ["c0"]  # 1.5 x 60 characters are reached after it
    assert result.sentences == 2 and result.cut == 2
