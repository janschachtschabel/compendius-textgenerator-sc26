"""The LLM check of part 2 (D58): the model rates every curriculum element the rules found; a 0 leaves the text."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.domain.requests import PRESETS
from app.knowledge.curriculum_check import BATCH_SIZE, LEFT_OUT, CurriculumCheckJob, check_curriculum
from app.llm.prompts import get_prompt
from tests.test_lehrplan_render import SN, _match
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

ELEMENTS = [
    _match("sn:k1", "Lichtbrechung an Linsen", ["kompetenz"], SN, "Lernbereich 2: Optik", ["Klassenstufe 7"]),
    _match("sn:k2", "Solarzelle als Energiewandler", ["inhalt"], SN, "Lernbereich 5: Energie", ["Klassenstufe 9"]),
    _match("sn:k3", "Protokoll führen", ["inhalt"], SN, "Lernbereich 2: Optik", ["Klassenstufe 7"], heading_only=True),
]


def rating(notes: dict[str, int]) -> Callable[[dict[str, Any]], str]:
    return lambda body: json.dumps(notes)


def job_for(fake: FakeBApi, per_request: int = 20_000) -> CurriculumCheckJob:
    gateway = make_gateway(fake, per_request=per_request)
    return CurriculumCheckJob(gateway.client, gateway.open_budget(), topic="Optik", subjects=("Physik",))


def test_the_model_drops_what_it_rates_0_and_the_rest_carries_its_note() -> None:
    fake = FakeBApi(rating({"e1": 2, "e2": 0, "e3": 1}))
    kept, report = check_curriculum(job_for(fake), ELEMENTS)
    assert [(match.hit.iri, match.note) for match in kept] == [("sn:k1", 2), ("sn:k3", 1)]
    assert report.rated == 3 and report.answered == 3 and report.dropped == 1 and report.calls == 1
    assert report.total_tokens > 0 and report.prompts == [get_prompt("curriculum_check").tag]


def test_the_prompt_names_topic_and_subject_and_each_element_with_its_area_and_curriculum() -> None:
    fake = FakeBApi(rating({"e1": 2, "e2": 2, "e3": 2}))
    check_curriculum(job_for(fake), ELEMENTS)
    prompt = json.dumps(fake.bodies[0]["messages"], ensure_ascii=False)
    assert "Optik" in prompt and "Physik" in prompt
    assert (
        "e2: „Solarzelle als Energiewandler“ · Bereich: Lernbereich 5: Energie · Lehrplan: Gymnasium Physik" in prompt
    )


def test_an_element_the_answer_leaves_out_stays_unrated() -> None:
    fake = FakeBApi(rating({"e1": 0, "e3": 2}))
    kept, report = check_curriculum(job_for(fake), ELEMENTS)
    assert [(match.hit.iri, match.note) for match in kept] == [("sn:k2", None), ("sn:k3", 2)]
    assert report.answered == 2 and report.fallbacks == {LEFT_OUT: 1}


def test_an_unreadable_answer_keeps_every_element_as_the_rules_found_it() -> None:
    kept, report = check_curriculum(job_for(FakeBApi(lambda body: "keine Ahnung")), ELEMENTS)
    assert kept == ELEMENTS and report.answered == 0 and report.dropped == 0
    assert sum(report.fallbacks.values()) == 3


def test_a_call_the_budget_cannot_hold_is_not_made_and_the_rules_decide() -> None:
    fake = FakeBApi(rating({"e1": 0}))
    kept, report = check_curriculum(job_for(fake, per_request=10), ELEMENTS)
    assert fake.bodies == [] and kept == ELEMENTS and sum(report.fallbacks.values()) == 3


def test_many_elements_go_to_the_model_in_batches() -> None:
    many = [_match(f"sn:{i}", f"Element {i}", ["inhalt"], SN, "Lernbereich 2: Optik") for i in range(BATCH_SIZE + 5)]
    fake = FakeBApi(rating({f"e{number}": 2 for number in range(1, BATCH_SIZE + 1)}))
    kept, report = check_curriculum(job_for(fake), many)
    assert len(fake.bodies) == 2 and report.calls == 2
    assert len(kept) == BATCH_SIZE + 5 and all(match.note == 2 for match in kept)


def test_nothing_to_check_asks_nothing() -> None:
    fake = FakeBApi(rating({}))
    kept, report = check_curriculum(job_for(fake), [])
    assert kept == [] and report.calls == 0 and fake.bodies == []


def test_the_profiles_that_pay_for_an_llm_check_the_curriculum_elements() -> None:
    """D58 (Jan): the rules in llm-free and balanced, the LLM check in the two best-quality profiles."""
    assert {name: preset["curriculum_check"] for name, preset in PRESETS.items()} == {
        "llm-free": "rule-based",
        "balanced": "rule-based",
        "best-quality": "llm",
        "best-quality-generated": "llm",
    }
