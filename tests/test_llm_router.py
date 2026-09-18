"""Doubtful matching cases: the policy reports them, the LLM router decides, the policy applies overrides."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.domain.models import Chunk, ScoredChunk, Source, SourceRole
from app.llm.budget import TokenBudget
from app.llm.client import BApiClient
from app.matching.policy import Doubt, assign
from app.matching.router import LlmRouter, RoutingResult
from app.templates.schema import Template, TemplateSlot
from tests.test_llm_client import BASE, KEY, FakeBApi

TEMPLATE = Template(
    id="two",
    name="Zwei Bausteine",
    slots=[
        TemplateSlot(id="t_a", slot="alpha", title="A · Alpha", description="Grundlagen und Begriffe"),
        TemplateSlot(id="t_b", slot="beta", title="B · Beta", description="Anwendungen und Praxis"),
    ],
)
SOURCE = Source(
    source_id="wikipedia:Test", project="wikipedia", role=SourceRole.LEITQUELLE, title="Test", url="u", is_primary=True
)
SOURCES = {SOURCE.source_id: SOURCE}


def _chunk(cid: str, text: str, **kwargs: Any) -> Chunk:
    return Chunk(
        chunk_id=cid,
        source_id=SOURCE.source_id,
        heading="Abschnitt",
        heading_path=["Abschnitt"],
        heading_level=2,
        text=text,
        **kwargs,
    )


def _fused(scores: dict[str, tuple[float, float]], chunks: dict[str, Chunk]) -> dict[str, list[ScoredChunk]]:
    return {
        "t_a": [ScoredChunk(chunk=chunks[cid], score=a, matcher="fused") for cid, (a, _) in scores.items()],
        "t_b": [ScoredChunk(chunk=chunks[cid], score=b, matcher="fused") for cid, (_, b) in scores.items()],
    }


CHUNKS = {
    "d1": _chunk("d1", "Linsen bündeln Licht; Brillen und Kameras nutzen diese Wirkung im Alltag."),
    "s1": _chunk("s1", "Ein Begriff bezeichnet hier den Gegenstand des Fachs."),
    "x1": _chunk("x1", "Anwendungen im Labor.", lexicon_slot="alpha"),
    "w1": _chunk("w1", "Schwacher Absatz ohne klares Signal."),
}
SCORES = {"d1": (0.62, 0.58), "s1": (0.9, 0.3), "x1": (0.5, 0.48), "w1": (0.3, 0.28)}


def test_policy_reports_doubtful_chunks_with_their_candidates() -> None:
    result = assign(TEMPLATE, list(CHUNKS.values()), _fused(SCORES, CHUNKS), SOURCES, confident_score=0.45)
    doubts = {d.chunk_id: d for d in result.doubtful}
    assert set(doubts) == {"d1"}, "only a close call without lexicon hit is doubtful"
    doubt = doubts["d1"]
    assert isinstance(doubt, Doubt)
    assert [slot for slot, _ in doubt.candidates] == ["t_a", "t_b"]
    assert doubt.margin == pytest.approx(0.04)
    assert result.classified["d1"] == "t_a" and result.classified["x1"] == "t_a"
    assert "w1" not in result.classified  # below the confidence threshold and no default slot


def test_overrides_move_the_chunk_and_count_as_confident() -> None:
    result = assign(
        TEMPLATE, list(CHUNKS.values()), _fused(SCORES, CHUNKS), SOURCES, overrides={"d1": "t_b", "w1": "t_b"}
    )
    assert result.classified["d1"] == "t_b" and result.classified["w1"] == "t_b"
    assert {sc.chunk.chunk_id for sc in result.assigned["t_b"]} == {"d1", "w1"}
    routed = next(sc for sc in result.assigned["t_b"] if sc.chunk.chunk_id == "d1")
    assert "LLM-Router" in " ".join(routed.reasons)
    assert not result.doubtful, "a routed chunk is no longer doubtful"


def test_unknown_override_targets_are_ignored() -> None:
    result = assign(
        TEMPLATE, list(CHUNKS.values()), _fused(SCORES, CHUNKS), SOURCES, confident_score=0.45, overrides={"d1": "nope"}
    )
    assert result.classified["d1"] == "t_a"


def _router(fake: FakeBApi, **kwargs: Any) -> LlmRouter:
    client = BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))
    return LlmRouter(client, **kwargs)


def _budget() -> Any:
    return TokenBudget(per_request=20_000, daily=2_000_000).open_request()


DOUBTS = [
    Doubt(chunk_id="d1", candidates=[("t_a", 0.62), ("t_b", 0.58)]),
    Doubt(chunk_id="d2", candidates=[("t_b", 0.55), ("t_a", 0.54)]),
    Doubt(chunk_id="d3", candidates=[("t_a", 0.7), ("t_b", 0.62)]),
]
MORE = {**CHUNKS, "d2": _chunk("d2", "Zweiter Zweifelsfall."), "d3": _chunk("d3", "Dritter Zweifelsfall.")}


def test_router_asks_once_and_keeps_only_valid_decisions() -> None:
    fake = FakeBApi(lambda body: 'Hier die Zuordnung: {"d1": "t_b", "d2": "zzz", "ghost": "t_a"} fertig.')
    result = _router(fake).route(DOUBTS[:2], MORE, TEMPLATE, _budget())
    assert isinstance(result, RoutingResult)
    assert result.overrides == {"d1": "t_b"}
    assert result.considered == 2 and result.routed == 1 and result.calls == 1 and result.total_tokens == 24
    assert result.moved == 1, "d1 left the policy's first choice t_a"
    user = fake.bodies[0]["messages"][1]["content"]
    assert "t_a" in user and "t_b" in user and "Linsen bündeln Licht" in user and "Zweiter Zweifelsfall" in user


def test_router_takes_the_closest_calls_first_up_to_max_chunks() -> None:
    fake = FakeBApi(lambda body: json.dumps({"d2": "t_a", "d1": "t_b"}))
    result = _router(fake, max_chunks=2).route(DOUBTS, MORE, TEMPLATE, _budget())
    user = fake.bodies[0]["messages"][1]["content"]
    assert "d2" in user and "d1" in user and "Dritter Zweifelsfall" not in user
    assert result.considered == 2 and result.overrides == {"d2": "t_a", "d1": "t_b"}


def test_router_skips_on_api_error_or_exhausted_budget() -> None:
    result = _router(FakeBApi(statuses=[400])).route(DOUBTS[:1], MORE, TEMPLATE, _budget())
    assert result.overrides == {} and result.skipped is not None and "b-api" in result.skipped

    fake = FakeBApi(lambda body: json.dumps({"d1": "t_b"}))
    tiny = TokenBudget(per_request=10, daily=2_000_000).open_request()
    result = _router(fake).route(DOUBTS[:1], MORE, TEMPLATE, tiny)
    assert result.overrides == {} and result.skipped is not None and "Budget" in result.skipped
    assert fake.requests == []


def test_router_without_doubts_makes_no_call() -> None:
    fake = FakeBApi(lambda body: "{}")
    result = _router(fake).route([], MORE, TEMPLATE, _budget())
    assert result.overrides == {} and result.calls == 0 and fake.requests == []


def test_router_counts_only_changed_assignments_as_moved() -> None:
    fake = FakeBApi(lambda body: json.dumps({"d1": "t_a", "d2": "t_a"}))
    result = _router(fake).route(DOUBTS[:2], MORE, TEMPLATE, _budget())
    assert result.overrides == {"d1": "t_a", "d2": "t_a"} and result.routed == 2
    assert result.moved == 1, "d1 was confirmed, d2 moved from t_b to t_a"
