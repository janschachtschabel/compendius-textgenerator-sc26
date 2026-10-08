"""matcher=llm (D34): the model assigns every paragraph; where it cannot, the rule-based decision stays."""

from __future__ import annotations

import json
import math
import re
import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx
import pytest

from app.compendium.prepared import PreparedTopic
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
    _combine,
    assign_with_llm,
    parse_assignment,
    render_messages,
)
from app.matching.policy import AssignmentResult
from app.service import CompendiumService
from app.templates.schema import ACTORS_KEY
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
    generated = prepared.template.generated_keys()
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


def test_an_unreadable_answer_is_asked_once_more_and_a_readable_second_one_decides(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    """M48: four of 27 runs with matcher llm lost a batch of 50 paragraphs to one unreadable answer. Since D70 every
    call gets a fresh answer, so the batch is asked once more before the rules take it (M49, V4; 07 point 12c)."""
    readable = answer_with("praxis", 0.9)
    seen: dict[str, int] = {}

    def first_unreadable(body: dict[str, Any]) -> str:
        batch = body["messages"][1]["content"]
        seen[batch] = seen.get(batch, 0) + 1
        return "Das kann ich nicht sagen." if seen[batch] == 1 else readable(body)

    fake = FakeBApi(first_unreadable)
    assignment, report = run(prepared, rule_based, make_job(fake))

    batches = math.ceil(len(offered) / BATCH_SIZE)
    praxis = prepared.template.slot_by_key("praxis")
    assert praxis is not None
    assert report.answered == report.paragraphs == len(offered) and report.fallback == 0
    assert assignment.classified == {chunk.chunk_id: praxis.id for chunk in offered}
    assert len(fake.bodies) == 2 * batches and report.asked_again == batches and report.calls == 2 * batches


def test_a_second_unreadable_answer_leaves_the_batch_to_the_rules_without_a_third_question(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    fake = FakeBApi(lambda body: "Das kann ich nicht sagen.")
    assignment, report = run(prepared, rule_based, make_job(fake))

    batches = math.ceil(len(offered) / BATCH_SIZE)
    assert len(fake.bodies) == 2 * batches and report.asked_again == batches
    assert report.answered == 0 and assignment is rule_based


def test_with_the_response_cache_of_the_b_api_an_unreadable_answer_is_not_asked_again(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    """Review 2026-10-02: with B_API_RESPONSE_CACHE the same question gets the stored answer again (D70)."""
    fake = FakeBApi(lambda body: "Das kann ich nicht sagen.")
    job = make_job(fake)
    job = replace(
        job,
        client=BApiClient(
            BASE, KEY, provider="openai", model="gpt-5.6-luna", response_cache=True, transport=httpx.MockTransport(fake)
        ),
    )
    assignment, report = run(prepared, rule_based, job)

    assert len(fake.bodies) == math.ceil(len(offered) / BATCH_SIZE) and report.asked_again == 0
    assert assignment is rule_based


def test_a_second_question_the_budget_turns_away_is_not_counted_and_the_first_call_is(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 2026-10-02: asked_again counted a second question the budget refused before any call, and the report
    lost the prompt and the model of the first call, which was made."""
    monkeypatch.setattr("app.matching.llm_assignment.BATCH_SIZE", len(offered))  # one batch
    fake = FakeBApi(lambda body: "Das kann ich nicht sagen.")
    job = make_job(fake)
    messages = render_messages(prepared.template, job.topic, offered, prepared.sources_by_id)
    reserved = estimate_tokens("".join(m["content"] for m in messages)) + job.client.completion_limit(
        OUTPUT_TOKENS_PER_PARAGRAPH * len(offered)
    )
    # room for the first question; the 24 tokens it spends leave too little for the second
    assignment, report = run(prepared, rule_based, make_job(fake, per_request=reserved + 10))

    assert len(fake.bodies) == 1 and report.asked_again == 0 and assignment is rule_based
    assert report.prompts == {get_prompt("paragraph_assignment").tag} and report.model == "gpt-5.6-luna"


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

    def reserve(self, tokens: int, wait_s: float | None = 0.0) -> str | None:
        self.asked.append(tokens)
        if len(self.asked) >= self.batches:
            self.all_asked.set()
        return super().reserve(tokens, wait_s)


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
    other_topic = render_messages(prepared.template, "Akustik", chunks, sources)[0]["content"]

    # D69: the blocks and the rules stand in the system message, the one part the provider's prompt cache keeps
    assert system.startswith(get_prompt("paragraph_assignment").system) and system == other_topic
    assert user.startswith("Thema des Kompendiums: Optik\n\nAbsätze:\n")
    for slot in prepared.template.content_slots():
        assert f"- {slot.slot} ({slot.title}): {slot.description}" in system
        assert f"Gehört nicht hinein: {slot.exclusions}" in system
    for slot in prepared.template.slots:
        if slot.is_generated:
            assert f"- {slot.slot} (" not in system
    assert prepared.template.assignment_rules and prepared.template.assignment_rules in system
    offered = {alias: (title, role) for alias, title, role, _ in PARAGRAPH_RE.findall(user)}
    assert offered["p1"] == (sources[primary.source_id].title, "Hauptartikel")
    assert offered["p2"] == (sources[twin.source_id].title, f"dasselbe Thema aus {sources[twin.source_id].project}")
    text = " ".join(long_one.text.split())
    assert len(text) > TEXT_CHARS and text[:TEXT_CHARS] in user and text[: TEXT_CHARS + 1] not in user


def test_the_prompt_asks_for_a_line_per_paragraph() -> None:
    """M77: lines like "p1 fachinhalte 8" in place of a JSON object - as good on the gold, a fifth to a third faster (D93)."""
    prompt = get_prompt("paragraph_assignment")

    assert prompt.version == 3
    assert prompt.system.endswith("zum Beispiel:\np1 fachinhalte 8\np2 keiner 9")
    assert prompt.user.endswith("Gib die Zeilen zurück.")


def test_parse_assignment_reads_a_line_per_paragraph() -> None:
    answer = "p1 fachinhalte 8\np2: keiner, 9\np3 Praxis 9\n- p4 praxis 5\np5 praxis hoch\np6 praxis\np7 praxis ²\np¹ praxis 8\np8 praxis 85"

    assert parse_assignment(answer) == {
        "p1": ("fachinhalte", 8 / 9),
        "p2": ("keiner", 1.0),
        "p3": ("praxis", 1.0),
        "p4": ("praxis", 5 / 9),
        "p8": ("praxis", 0.85),  # a percentage
    }


def test_a_line_in_another_form_is_read_as_meant() -> None:
    """Review 2026-10-08: only the first digit was read - "0.8" gave 0.0 and "10" 0.11, below the rules' paragraphs -
    and "P12", "**p12**" or a numbered line were skipped."""
    answer = "\n".join(
        [
            "p1 praxis 0.8",
            "p2 praxis 0,8",
            "p3 praxis 10",
            "P4 praxis 7",
            "**p5** praxis 9",
            "1. p6 praxis 9",
            "p07 x 9",
        ]
    )

    assert parse_assignment(answer) == {
        "p1": ("praxis", 0.8),
        "p2": ("praxis", 0.8),
        "p3": ("praxis", 1.0),
        "p4": ("praxis", 7 / 9),
        "p5": ("praxis", 1.0),
        "p6": ("praxis", 1.0),
        "p7": ("x", 1.0),
    }


def test_the_model_decides_every_paragraph_it_answers_in_lines(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    def lines(body: dict[str, Any]) -> str:
        return "\n".join(f"{alias} fachinhalte 8" for alias, *_ in PARAGRAPH_RE.findall(body["messages"][1]["content"]))

    assignment, report = run(prepared, rule_based, make_job(FakeBApi(lines)))

    fachinhalte = prepared.template.slot_by_key("fachinhalte")
    assert fachinhalte is not None
    assert report.answered == len(offered) and report.fallback == 0 and report.asked_again == 0
    assert assignment.classified == {chunk.chunk_id: fachinhalte.id for chunk in offered}


def test_parse_assignment_reads_blocks_and_confidences() -> None:
    """The JSON object of version 2, which a model may still give, is read where the answer holds no line."""
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


def test_a_block_key_in_capitals_is_understood(
    prepared: PreparedTopic, rule_based: AssignmentResult, offered: list[Chunk]
) -> None:
    """KO-07: the answer was compared in lower case and the keys of a template as written, so a block of a custom
    template named "Praxis" was unknown to every answer - its tokens bought nothing and the rules decided."""
    slots = [s.model_copy(update={"slot": "Praxis"}) if s.slot == "praxis" else s for s in prepared.template.slots]
    capital = replace(prepared, template=prepared.template.model_copy(update={"slots": slots}))
    assignment, report = run(capital, rule_based, make_job(FakeBApi(answer_with("praxis", 0.9))))

    praxis = capital.template.slot_by_key("Praxis")
    assert praxis is not None
    assert report.unknown_keys == 0 and report.answered == len(offered)
    assert assignment.classified == {chunk.chunk_id: praxis.id for chunk in offered}


def test_a_paragraph_the_rules_kept_does_not_push_out_the_models_choice() -> None:
    """KO-12: the model's confidence runs from 0 to 1, the policy's score up to 2.0; where a batch failed, its
    paragraphs kept the policy's score and won the budget cut over what the model chose."""
    from app.domain.models import Chunk
    from app.templates.schema import SlotBudget, Template, TemplateSlot

    slot = TemplateSlot(id="s", slot="praxis", title="Praxis", budget=SlotBudget(min_chunks=1, max_chunks=1))
    template = Template(id="t", name="t", slots=[slot])
    chosen, kept_by_rules = (
        Chunk(chunk_id=f"wikipedia:Optik:c00{n}", source_id="wikipedia:Optik", heading="H", heading_path=["H"],
              heading_level=2, text="Ein Absatz.", position=n)
        for n in (1, 2)
    )  # fmt: skip
    rules = AssignmentResult(
        assigned={},
        unassigned=0,
        classified={kept_by_rules.chunk_id: "s"},
        slot_scores={"s": {kept_by_rules.chunk_id: 1.2}},
    )
    result = _combine(template, [chosen, kept_by_rules], {chosen.chunk_id: ("s", 0.6)}, rules, skipped=0)
    assert [item.chunk.chunk_id for item in result.assigned["s"]] == [chosen.chunk_id]


def test_person_paragraphs_stay_with_an_actors_block_of_any_name(
    prepared: PreparedTopic, rule_based: AssignmentResult
) -> None:
    """WA-07 (audit 2026-09-28): the rules keep the shared lexicon's persons for the actors block whatever the
    template calls it; matcher=llm offered them to the model when the block had another name, and they cost tokens
    and landed in a content block."""
    slots = [
        slot.model_copy(update={"slot": "persoenlichkeiten"}) if slot.generator == "actors" else slot
        for slot in prepared.template.slots
    ]
    template = prepared.template.model_copy(update={"slots": slots})
    primary = prepared.primary
    assert primary is not None
    person = Chunk(
        chunk_id=f"{primary.source_id}:c900",
        source_id=primary.source_id,
        heading="Bekannte Vertreter",
        heading_path=["Bekannte Vertreter"],
        heading_level=2,
        text="Ernst Abbe entwickelte die Theorie der Bildentstehung im Mikroskop und gründete eine Stiftung.",
        position=900,
        lexicon_slot=ACTORS_KEY,
    )
    fake = FakeBApi(answer_with("fachinhalte"))

    result, report = assign_with_llm(
        template, [*prepared.chunks, person], prepared.sources_by_id, rule_based, make_job(fake)
    )

    assert all(person.text not in json.dumps(body, ensure_ascii=False) for body in fake.bodies)
    assert person.chunk_id not in result.classified
    assert report.paragraphs == len([c for c in prepared.chunks if c.lexicon_slot not in template.generated_keys()])
