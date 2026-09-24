"""matcher=llm (D34): the model assigns every paragraph; where it cannot, the rule-based decision stays."""

from __future__ import annotations

import json
import math
import re
import threading
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.domain.models import Chunk
from app.domain.requests import GenerateRequest
from app.llm.budget import RequestBudget, TokenBudget, estimate_tokens
from app.llm.client import BApiClient
from app.llm.prompts import get_prompt
from app.matching.llm_assignment import (
    BATCH_SIZE,
    OUTPUT_TOKENS_PER_PARAGRAPH,
    TEXT_CHARS,
    AssignmentJob,
    assign_with_llm,
    parse_assignment,
    render_messages,
)
from app.matching.policy import AssignmentResult
from app.service import CompendiumService, PreparedTopic
from tests.test_llm_client import BASE, KEY, FakeBApi

PARAGRAPH_RE = re.compile(r"^(p\d+) \(Artikel: (.+?), (.+?); Abschnitt: (.+?)\):$", re.MULTILINE)


def answer_with(
    slot_key: str | Callable[[int], tuple[str, float]],
    confidence: float = 0.8,
    *,
    omit: frozenset[str] = frozenset(),
    extra: dict[str, Any] | None = None,
) -> Callable[[dict[str, Any]], str]:
    """Answers every offered paragraph with ``slot_key``; a callable gets the number of the paragraph in its batch."""

    def responder(body: dict[str, Any]) -> str:
        user = body["messages"][1]["content"]
        answer: dict[str, Any] = {}
        for alias, *_ in PARAGRAPH_RE.findall(user):
            if alias in omit:
                continue
            number = int(alias[1:])
            answer[alias] = list(slot_key(number)) if callable(slot_key) else [slot_key, confidence]
        answer.update(extra or {})
        return json.dumps(answer)

    return responder


def make_job(fake: FakeBApi, per_request: int = 1_000_000, concurrency: int = 1) -> AssignmentJob:
    client = BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))
    budget = TokenBudget(per_request=per_request, daily=10_000_000).open_request()
    return AssignmentJob(client=client, budget=budget, topic="Optik", concurrency=concurrency)


@pytest.fixture(scope="module")
def prepared(service: CompendiumService) -> PreparedTopic:
    return service.prepare(GenerateRequest(topic="Optik", parts=["world"]))


@pytest.fixture(scope="module")
def rule_based(service: CompendiumService, prepared: PreparedTopic) -> AssignmentResult:
    return service.match(prepared, "hybrid_light", 12_000).assignment


@pytest.fixture(scope="module")
def offered(prepared: PreparedTopic) -> list[Chunk]:
    """The paragraphs the model gets: all except material of generated blocks, which the policy skips as well."""
    generated = {slot.slot for slot in prepared.template.slots if slot.is_generated}
    return [chunk for chunk in prepared.chunks if chunk.lexicon_slot not in generated]


def run(prepared: PreparedTopic, rule_based: AssignmentResult, job: AssignmentJob) -> Any:
    return assign_with_llm(prepared.template, prepared.chunks, prepared.sources_by_id, rule_based, job)


def test_the_model_decides_every_paragraph_it_answers(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    fake = FakeBApi(answer_with("praxis", 0.9))
    assignment, report = run(prepared, rule_based, make_job(fake))

    praxis = prepared.template.slot_by_key("praxis")
    assert praxis is not None
    assert report.paragraphs == report.answered == len(offered) > BATCH_SIZE
    assert report.fallback == 0 and report.fallbacks == {} and report.unknown_keys == 0
    assert assignment.classified == {chunk.chunk_id: praxis.id for chunk in offered}
    assert len(fake.bodies) == report.calls == math.ceil(len(offered) / BATCH_SIZE)
    assert report.total_tokens == 24 * report.calls
    assert report.prompts == {get_prompt("paragraph_assignment").tag}
    kept = assignment.assigned[praxis.id]
    assert 0 < len(kept) <= praxis.budget.max_chunks and all(item.matcher == "llm" for item in kept)
    assert not any(items for slot_id, items in assignment.assigned.items() if slot_id != praxis.id)


def test_keiner_keeps_a_paragraph_out_of_every_block(prepared: PreparedTopic, rule_based: AssignmentResult) -> None:
    assert rule_based.classified, "the policy assigns paragraphs the model then leaves out"
    assignment, report = run(prepared, rule_based, make_job(FakeBApi(answer_with("keiner"))))
    assert report.answered == report.paragraphs and report.fallback == 0
    assert assignment.classified == {} and not any(assignment.assigned.values())


def test_a_failed_call_keeps_the_rule_based_decision_for_its_paragraphs(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    fake = FakeBApi(answer_with("praxis"), statuses=[400])  # the first batch fails for good (400 is not retried)
    assignment, report = run(prepared, rule_based, make_job(fake))

    first, rest = offered[:BATCH_SIZE], offered[BATCH_SIZE:]
    assert report.fallback == len(first) and report.answered == len(rest)
    [(reason, count)] = report.fallbacks.items()
    assert reason.startswith("b-api") and count == len(first)
    for chunk in first:
        assert assignment.classified.get(chunk.chunk_id) == rule_based.classified.get(chunk.chunk_id)
    praxis = prepared.template.slot_by_key("praxis")
    assert praxis is not None and all(assignment.classified[chunk.chunk_id] == praxis.id for chunk in rest)


def test_an_unknown_block_or_a_missing_paragraph_falls_back_alone(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    fake = FakeBApi(answer_with("praxis", omit=frozenset({"p2"}), extra={"p1": ["erfundener_baustein", 0.9]}))
    assignment, report = run(prepared, rule_based, make_job(fake))

    batches = [offered[i : i + BATCH_SIZE] for i in range(0, len(offered), BATCH_SIZE)]
    assert report.unknown_keys == len(batches)
    assert report.fallback == sum(min(2, len(batch)) for batch in batches)
    assert len(report.fallbacks) == 2  # one reason for unknown blocks, one for paragraphs the answer left out
    for batch in batches:
        for chunk in batch[:2]:
            assert assignment.classified.get(chunk.chunk_id) == rule_based.classified.get(chunk.chunk_id)


def test_an_unreadable_answer_leaves_the_rule_based_assignment(
    prepared: PreparedTopic, rule_based: AssignmentResult
) -> None:
    assignment, report = run(prepared, rule_based, make_job(FakeBApi(lambda body: "Das kann ich nicht sagen.")))
    assert report.answered == 0 and report.fallback == report.paragraphs
    assert all(reason.startswith("unlesbare Antwort") for reason in report.fallbacks)
    assert assignment is rule_based


def test_a_spent_budget_stops_before_any_call(prepared: PreparedTopic, rule_based: AssignmentResult) -> None:
    fake = FakeBApi(answer_with("praxis"))
    assignment, report = run(prepared, rule_based, make_job(fake, per_request=10))
    assert fake.bodies == [] and report.calls == 0 and report.answered == 0
    assert assignment is rule_based


class CountingBudget(RequestBudget):
    """A request budget that notes every reservation asked for; ``all_asked`` is set once each batch has asked."""

    def __init__(self, limit: int, batches: int) -> None:
        super().__init__(TokenBudget(per_request=limit, daily=10_000_000), limit)
        self.asked: list[int] = []
        self.batches = batches
        self.all_asked = threading.Event()

    def reserve(self, tokens: int, **kwargs: Any) -> str | None:
        self.asked.append(tokens)
        if len(self.asked) >= self.batches:
            self.all_asked.set()
        return super().reserve(tokens, **kwargs)


def test_batches_the_budget_cannot_hold_at_once_take_turns_instead_of_falling_back(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    """M13: every batch reserved about 13,000 tokens and spent about 8,000; with a budget of 60,000 the batches beyond
    the fourth fell back to the rules at once, 194 of 1,053 paragraphs in three of five topics."""
    batches = math.ceil(len(offered) / BATCH_SIZE)
    first = render_messages(prepared.template, "Optik", offered[:BATCH_SIZE], prepared.sources_by_id)
    fake = FakeBApi()
    job = make_job(fake, concurrency=batches)
    full = estimate_tokens("".join(m["content"] for m in first)) + job.client.completion_limit(
        OUTPUT_TOKENS_PER_PARAGRAPH * BATCH_SIZE
    )
    budget = job.budget = CountingBudget(limit=full * 3 // 2, batches=batches)  # room for one full batch at a time

    def answer_once_every_batch_asked(body: dict[str, Any]) -> str:  # the calls overlap as real ones do
        budget.all_asked.wait(10)
        return answer_with("praxis")(body)

    fake.responder = answer_once_every_batch_asked
    _, report = run(prepared, rule_based, job)

    assert sum(sorted(budget.asked)[-2:]) > budget.limit, "two batches cannot hold their reservations at once"
    assert report.fallbacks == {} and report.answered == report.paragraphs == len(offered)
    assert report.calls == len(fake.bodies) == batches and budget.used == 24 * batches


def test_a_block_keeps_the_paragraphs_the_model_is_surest_about(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    def descending(number: int) -> tuple[str, float]:
        return "fachinhalte", round(1 - number / 100, 2)

    assignment, _ = run(prepared, rule_based, make_job(FakeBApi(answer_with(descending))))

    confidence = {chunk.chunk_id: round(1 - (index % BATCH_SIZE + 1) / 100, 2) for index, chunk in enumerate(offered)}
    slot = prepared.template.slot_by_key("fachinhalte")
    assert slot is not None
    kept = {item.chunk.chunk_id for item in assignment.assigned[slot.id]}
    dropped = [chunk_id for chunk_id in confidence if chunk_id not in kept]
    assert kept and dropped, "the budget of the block has to cut something for this test"
    assert min(confidence[c] for c in kept) >= max(confidence[c] for c in dropped)


def test_the_prompt_offers_the_blocks_the_rules_and_each_paragraph(prepared: PreparedTopic) -> None:
    sources = prepared.sources_by_id
    primary = next(chunk for chunk in prepared.chunks if sources[chunk.source_id].is_primary)
    twin = next(chunk for chunk in prepared.chunks if sources[chunk.source_id].origin == "same_topic")
    long_one = max(prepared.chunks, key=lambda chunk: len(chunk.text))
    chunks = [primary, twin, long_one]
    system, user = (message["content"] for message in render_messages(prepared.template, "Optik", chunks, sources))

    assert system == get_prompt("paragraph_assignment").system
    assert user.startswith("Thema des Kompendiums: Optik\n\nBausteine:\n")
    for slot in prepared.template.content_slots():
        assert f"- {slot.slot} ({slot.title}): {slot.description}" in user
        assert f"Gehört nicht hinein: {slot.exclusions}" in user
    for slot in prepared.template.slots:
        if slot.is_generated:
            assert f"- {slot.slot} (" not in user
    assert prepared.template.assignment_rules and prepared.template.assignment_rules in user
    offered = {alias: (title, role) for alias, title, role, _ in PARAGRAPH_RE.findall(user)}
    assert offered["p1"] == (sources[primary.source_id].title, "Hauptartikel")
    assert offered["p2"] == (sources[twin.source_id].title, f"dasselbe Thema aus {sources[twin.source_id].project}")
    text = " ".join(long_one.text.split())
    assert len(text) > TEXT_CHARS and text[:TEXT_CHARS] in user and text[: TEXT_CHARS + 1] not in user


def test_parse_assignment_reads_blocks_and_confidences() -> None:
    answer = (
        'Hier die Zuordnung: {"p1": ["Fachinhalte ", 0.8], "p2": ["keiner", "0.9"], "p3": ["praxis", 1.7], '
        '"p4": "praxis", "p5": ["praxis"], "p6": ["praxis", -0.2]}'
    )
    assert parse_assignment(answer) == {
        "p1": ("fachinhalte", 0.8),
        "p2": ("keiner", 0.9),
        "p3": ("praxis", 1.0),
        "p6": ("praxis", 0.0),
    }
    assert parse_assignment("Kein JSON in dieser Antwort.") is None
    assert parse_assignment('["p1", "p2"]') is None
    assert parse_assignment('{"p1": ["praxis", 0.8],}') is None  # not JSON
    assert parse_assignment('{"p1": ["praxis", "sicher"]}') == {}
