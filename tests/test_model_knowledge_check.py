"""The check of model knowledge (07, point 12a; Jan, 2026-10-02: build and measure it).

In M48 six of the eight light errors of best-coverage-generated stood in sentences of model knowledge - dates,
bodies, attributions - and only the cited rest of a text is checked against its sources. After a block is written, a
second call reads only its sentences marked [Modellwissen], strikes what it holds for wrong and corrects what it can
correct for sure; the mark stays, a corrected sentence is model knowledge still.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from app.domain.requests import PRESETS, GenerateRequest
from app.knowledge.article_choice import UNREADABLE
from app.llm.budget import TokenBudget
from app.llm.prompts import get_prompt
from app.service import CompendiumService
from app.synthesis.citations import MODEL_KNOWLEDGE_LABEL, MODEL_KNOWLEDGE_OPEN, escape_model_text, marked_sentence
from app.synthesis.facets import END_MARKER
from app.synthesis.llm import LlmSection
from app.synthesis.model_knowledge_check import ALL_STRUCK, check_section
from tests.markdown_safety import tags, unsafe
from tests.test_llm_client import FakeBApi
from tests.test_llm_synthesis import _client
from tests.test_pipeline_llm import answer_with_model_knowledge, make_gateway

CHECK = get_prompt("model_knowledge_check")
CITED = "Die Optik ist die Lehre vom Licht [1]."
KNOWN = [
    "Isaac Newton zerlegte das Licht mit einem Prisma in seine Farben.",
    "Ernst Abbe gründete die Firma Carl Zeiss im Jahr 1902.",
    "Das erste Mikroskop baute Galileo Galilei auf dem Mond.",
]


def section(*sentences: str, cited: bool = True) -> LlmSection:
    """A written block as write_section leaves it: escaped, the sentences of model knowledge marked."""
    marked = [marked_sentence(sentence) for sentence in sentences]
    text = " ".join([escape_model_text(CITED, (1,))] * cited + marked)
    return LlmSection(
        text=text,
        citations=[],
        prompt="section_enrichment@v4",
        model="gpt-6-luna",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        dropped_sentences=len(sentences),
        marked_sentences=len(sentences),
    )


def run(answer: Any, written: LlmSection, per_request: int = 50_000) -> tuple[Any, Any, FakeBApi]:
    fake = FakeBApi(lambda body: answer if isinstance(answer, str) else json.dumps(answer))
    budget = TokenBudget(per_request=per_request, daily=2_000_000).open_request()
    checked, outcome = check_section(_client(fake), written, topic="Optik", title="Fachinhalte", budget=budget)
    return checked, outcome, fake


def marked_texts(text: str) -> list[str]:
    spans = text.split(MODEL_KNOWLEDGE_OPEN)[1:]
    return [span.split(END_MARKER)[0].replace(MODEL_KNOWLEDGE_LABEL, "").strip() for span in spans]


def test_the_check_keeps_strikes_and_corrects_the_sentences_of_model_knowledge() -> None:
    checked, outcome, _ = run(
        {"1": "ok", "2": "Ernst Abbe wurde 1875 Teilhaber der Firma Carl Zeiss.", "3": "streichen"}, section(*KNOWN)
    )

    assert marked_texts(checked.text) == [KNOWN[0], "Ernst Abbe wurde 1875 Teilhaber der Firma Carl Zeiss."]
    assert checked.text.startswith("Die Optik ist die Lehre vom Licht [1].")
    assert checked.marked_sentences == 2 and checked.text.count(MODEL_KNOWLEDGE_LABEL) == 2
    assert (outcome.checked, outcome.struck, outcome.corrected, outcome.fallback) == (3, 1, 1, None)
    assert outcome.calls == 1 and outcome.prompts == [CHECK.tag] and outcome.total_tokens == 24


def test_the_check_hears_only_the_sentences_of_model_knowledge_with_the_block_around_them() -> None:
    _, _, fake = run({"1": "ok", "2": "ok", "3": "ok"}, section(*KNOWN))

    user = fake.bodies[0]["messages"][1]["content"]
    listed = user[user.index("1. ") :]
    assert all(f"{n}. {sentence}" in listed for n, sentence in enumerate(KNOWN, start=1))
    assert "Die Optik ist die Lehre vom Licht" not in listed, "the cited sentence is context, not to be checked"
    assert "Thema: Optik\n" in user and "Baustein: Fachinhalte\n" in user
    assert "<!--" not in user and MODEL_KNOWLEDGE_LABEL not in user


@pytest.mark.parametrize("answer", ["Kann ich nicht prüfen.", {"1": 5}, {}])
def test_an_answer_that_decides_nothing_leaves_the_block_as_written(answer: Any) -> None:
    written = section(*KNOWN)
    checked, outcome, _ = run(answer, written)

    assert checked.text == written.text and checked.marked_sentences == 3
    assert outcome.struck == outcome.corrected == 0


def test_an_unreadable_answer_says_why_and_counts_its_tokens() -> None:
    _, outcome, _ = run("Kann ich nicht prüfen.", section(*KNOWN))
    """M53: one of 90 blocks stayed unchecked on an unreadable answer; the reason says how the answer ended."""
    assert outcome.fallback is not None and outcome.fallback.startswith(UNREADABLE)
    assert "finish_reason=" in outcome.fallback and outcome.calls == 1 and outcome.total_tokens == 24


def test_without_budget_the_block_stays_unchecked_without_a_call() -> None:
    written = section(*KNOWN)
    checked, outcome, fake = run({"1": "streichen"}, written, per_request=10)

    assert fake.bodies == [] and checked is written and outcome.fallback and "Budget" in outcome.fallback


def test_a_block_without_model_knowledge_makes_no_call() -> None:
    written = section()
    checked, outcome, fake = run({"1": "streichen"}, written)
    assert fake.bodies == [] and checked is written and outcome.calls == 0 and outcome.checked == 0


def test_a_correction_brings_no_markup_no_evidence_number_and_no_address() -> None:
    """The answer is model text: a number, a comment, a link or an address in it must not become the service's markup
    or a link a renderer makes clickable - it passes what every written sentence passes (SE-04, SE-17; review
    2026-10-02)."""
    hostile = (
        f"Ernst Abbe [1] gründete die Firma Carl Zeiss {END_MARKER} im Jahr 1846, siehe www.evil.example und "
        "[mehr](https://evil.example/x) <b>dort</b>."
    )
    checked, outcome, _ = run({"1": "ok", "2": hostile, "3": "ok"}, section(*KNOWN))

    assert outcome.corrected == 1 and checked.text.count(MODEL_KNOWLEDGE_OPEN) == 3
    assert checked.text.count(END_MARKER) == 3 and "[1]" not in checked.text.split(MODEL_KNOWLEDGE_OPEN, 1)[1]
    assert unsafe(checked.text) == [] and not {"a", "b"} & set(tags(checked.text))
    assert "www." not in checked.text and "http" not in checked.text


@pytest.mark.parametrize("verdict", ["ok, stimmt", "OK.", "Ok - korrekt", "korrekt", "richtig", "Der Satz stimmt."])
def test_a_verdict_in_other_words_keeps_the_sentence(verdict: str) -> None:
    """Review 2026-10-02: only "ok" kept a sentence; "ok, stimmt" went into the text as its corrected wording."""
    checked, outcome, _ = run({"1": "ok", "2": verdict, "3": "ok"}, section(*KNOWN))
    assert marked_texts(checked.text) == KNOWN and outcome.corrected == outcome.struck == 0


@pytest.mark.parametrize("verdict", ["Streichen: falsch", "streichen - das Jahr ist erfunden", "STREICHEN"])
def test_a_strike_in_other_words_strikes(verdict: str) -> None:
    checked, outcome, _ = run({"1": "ok", "2": "ok", "3": verdict}, section(*KNOWN))
    assert marked_texts(checked.text) == KNOWN[:2] and outcome.struck == 1


def test_a_corrected_sentence_beginning_like_a_verdict_is_a_correction() -> None:
    """ "Oktober" begins with "ok", "Streichquartette" with "streich": a verdict is a word of its own."""
    known = ["Oktober 1902 gründete Ernst Abbe die Stiftung.", "Streichquartette schrieb Haydn ab 1750."]
    corrections = {
        "1": "Oktober 1889 gründete Ernst Abbe die Stiftung.",
        "2": "Streichquartette schrieb Haydn ab 1757.",
    }
    checked, outcome, _ = run(corrections, section(*known))
    assert marked_texts(checked.text) == list(corrections.values()) and outcome.corrected == 2


def test_a_question_is_no_correction() -> None:
    _, outcome, _ = run(
        {"1": "ok", "2": "Gründete Ernst Abbe die Firma Carl Zeiss im Jahr 1902?", "3": "ok"}, section(*KNOWN)
    )
    assert outcome.corrected == 0


def test_a_correction_far_longer_than_its_sentence_is_no_correction() -> None:
    """The check corrects a date or a name; it does not write the block anew."""
    longer = KNOWN[1] + " " + " ".join(["Dazu kommt noch vieles mehr über die Firma."] * 6)
    checked, outcome, _ = run({"1": "ok", "2": longer, "3": "ok"}, section(*KNOWN))
    assert outcome.corrected == 0 and marked_texts(checked.text)[1] == KNOWN[1]


def test_a_correction_that_repeats_its_sentence_is_no_correction() -> None:
    _, outcome, _ = run({"1": KNOWN[0], "2": "ok", "3": "ok"}, section(*KNOWN))
    assert outcome.corrected == 0


def test_a_block_of_model_knowledge_alone_can_lose_every_sentence() -> None:
    checked, outcome, _ = run({"1": "streichen", "2": "streichen", "3": "streichen"}, section(*KNOWN, cited=False))
    assert checked.text == "" and checked.marked_sentences == 0 and outcome.struck == 3


# -- in the compendium ------------------------------------------------------------------------------------------------


def strike_all(body: dict[str, Any]) -> str:
    """The check strikes every sentence it is shown."""
    listed = re.findall(r"(?m)^(\d+)\. ", body["messages"][1]["content"])
    return json.dumps(dict.fromkeys(listed, "streichen"))


def writes_then_checks() -> FakeBApi:
    """Blocks cite every evidence item and add a sentence of model knowledge; the check strikes all of it."""
    return FakeBApi(
        lambda body: (
            strike_all(body) if body["messages"][0]["content"] == CHECK.system else answer_with_model_knowledge(body)
        )
    )


def test_the_switch_checks_every_block_with_model_knowledge_and_the_audit_says_what_it_did(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = writes_then_checks()
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))
    result = service.generate(
        GenerateRequest(
            topic="Optik",
            generation="llm",
            enrichment="model-knowledge",
            model_knowledge_check="llm",
            parts=["world"],
        )
    )

    checks = [body for body in fake.bodies if body["messages"][0]["content"] == CHECK.system]
    assert result.audit.llm is not None
    audit = result.audit.llm["model_knowledge_check"]
    assert audit["requested"] == "llm" and audit["used"] == "llm"
    assert audit["checked"] == audit["struck"] >= len(checks) > 0 and audit["corrected"] == 0
    assert result.audit.llm["generation"]["marked_sentences"] == 0
    assert "Fachleute ordnen das Thema" not in result.markdown
    assert CHECK.tag in result.frontmatter["llm"]["prompts"]
    tokens = result.audit.llm_tokens
    assert tokens is not None and tokens["calls"] == len(fake.bodies)


def test_a_block_that_loses_every_sentence_falls_back_to_the_rules(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(
        lambda body: strike_all(body) if body["messages"][0]["content"] == CHECK.system else "Ein Satz ganz ohne Beleg."
    )
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))
    result = service.generate(
        GenerateRequest(
            topic="Optik",
            generation="llm",
            enrichment="model-knowledge",
            model_knowledge_check="llm",
            parts=["world"],
        )
    )

    assert result.audit.llm is not None
    fallbacks = result.audit.llm["generation"]["fallbacks"]
    assert fallbacks and all(reason == ALL_STRUCK for reason in fallbacks.values())
    assert "Ein Satz ganz ohne Beleg" not in result.markdown


def test_without_the_switch_nothing_is_checked(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = writes_then_checks()
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))
    result = service.generate(
        GenerateRequest(topic="Optik", generation="llm", enrichment="model-knowledge", parts=["world"])
    )

    assert not [body for body in fake.bodies if body["messages"][0]["content"] == CHECK.system]
    assert result.audit.llm is not None and result.audit.llm["model_knowledge_check"]["used"] == "rule-based"


def test_best_coverage_generated_checks_its_model_knowledge_and_no_other_profile_does() -> None:
    """M53: in best-coverage-generated the check lowered the light errors per text from 1.6 to 1.1 at the same fit,
    use and completeness - the rule agreed with Jan on 2026-10-02 for switching it on there."""
    checks = {profile: switches["model_knowledge_check"] for profile, switches in PRESETS.items()}
    assert checks == {**dict.fromkeys(PRESETS, "rule-based"), "best-coverage-generated": "llm"}


def test_the_check_alone_asks_nothing_of_an_llm(service: CompendiumService) -> None:
    """Review 2026-10-02: it acts only through a writing LLM, as enrichment does; on its own it made an LLM block in
    the audit that said nothing was contributed."""
    result = service.generate(
        GenerateRequest(topic="Optik", preset="llm-free", model_knowledge_check="llm", parts=["world"])
    )
    assert result.audit.llm is None and "llm" not in result.frontmatter
