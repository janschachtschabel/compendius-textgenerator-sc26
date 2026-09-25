"""LLM section synthesis: prompt registry, evidence block, citation verification, renumbering, fallbacks."""

from __future__ import annotations

from typing import Any

import httpx

from app.domain.models import Chunk, ScoredChunk, Source, SourceRole
from app.llm.budget import TokenBudget
from app.llm.call import LlmSkipped
from app.llm.client import REASONING_ALLOWANCE, BApiClient
from app.llm.prompts import PROMPTS, get_prompt
from app.synthesis.citations import (
    CONCLUSION,
    CONCLUSION_OPEN,
    MODEL_KNOWLEDGE,
    MODEL_KNOWLEDGE_LABEL,
    MODEL_KNOWLEDGE_OPEN,
    drop_unsupported,
    opening_marker,
    renumber,
    verify_citations,
    without_markers,
)
from app.synthesis.facets import END_MARKER
from app.synthesis.llm import (
    MAX_EVIDENCE_CHARS,
    LlmSection,
    LlmSynthesizer,
    evidence_block,
    shift_citations,
)
from app.templates.manager import TemplateManager
from tests.test_llm_client import BASE, KEY, FakeBApi

SOURCE = Source(
    source_id="wikipedia:Test", project="wikipedia", role=SourceRole.LEITQUELLE, title="Test", url="u", is_primary=True
)
SOURCES = {SOURCE.source_id: SOURCE}


def _chunk(cid: str, heading: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=cid,
        source_id=SOURCE.source_id,
        heading=heading,
        heading_path=[heading] if heading != "Einleitung" else [],
        heading_level=0 if heading == "Einleitung" else 2,
        is_lead=heading == "Einleitung",
        text=text,
    )


SCORED = [
    ScoredChunk(
        chunk=_chunk("c0", "Einleitung", "Das Thema ist ein Gebiet der Physik und handelt vom Licht."), score=1.0
    ),
    ScoredChunk(
        chunk=_chunk("c1", "Geschichte", "Im 17. Jahrhundert begann die Entwicklung der Fernrohre."), score=0.8
    ),
]
ANSWER = (
    "Erster Satz [1]. Zweiter Satz ohne Beleg. Dritter Satz mit falscher Nummer [9]. "
    "Vierter Satz [2] [9].\n\nFünfter Satz. [1]"
)


def _client(fake: FakeBApi) -> BApiClient:
    return BApiClient(BASE, KEY, provider="openai", model="gpt-5.6-luna", transport=httpx.MockTransport(fake))


def _slot() -> Any:
    return TemplateManager().get("sc26").slots[0]


def test_prompt_registry_has_versioned_prompts() -> None:
    assert {"section_synthesis", "passage_selection"} <= set(PROMPTS)
    prompt = get_prompt("section_synthesis")
    assert prompt.version >= 1 and prompt.tag == f"section_synthesis@v{prompt.version}"
    messages = prompt.render(
        topic="Thema",
        title="1 · Themendefinition",
        description="Was das Thema ist",
        inclusions="Kerndefinition",
        exclusions="Relevanz",
        sub_items="- Leitfragen",
        target_chars=1200,
        evidence="[1] (Test › Einleitung) Text",
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Thema" in messages[1]["content"] and "[1] (Test › Einleitung) Text" in messages[1]["content"]


def test_evidence_block_numbers_chunks_with_source_and_heading() -> None:
    long_chunk = ScoredChunk(chunk=_chunk("c9", "Lang", "x" * (MAX_EVIDENCE_CHARS + 50)), score=0.5)
    orphan = ScoredChunk(chunk=_chunk("c8", "Weg", "Quelle fehlt."), score=0.5)
    orphan.chunk.source_id = "nirgends"
    block, items = evidence_block([*SCORED, orphan, long_chunk], SOURCES)
    lines = block.splitlines()
    assert lines[0].startswith("[1] (Test › Einleitung) Das Thema ist")
    assert lines[1].startswith("[2] (Test › Geschichte) Im 17. Jahrhundert")
    assert lines[2].startswith("[3] (Test › Lang) xxx") and lines[2].endswith("…")
    assert len(lines[2]) < MAX_EVIDENCE_CHARS + 40
    assert [chunk.chunk_id for chunk, _ in items] == ["c0", "c1", "c9"]


def test_verify_citations_keeps_only_sentences_with_valid_markers() -> None:
    text, dropped = verify_citations(ANSWER, {1, 2})
    assert text == "Erster Satz [1]. Vierter Satz [2].\n\nFünfter Satz [1]."
    assert dropped == 2


def test_verify_citations_drops_headings_and_marker_only_lines() -> None:
    text, dropped = verify_citations("### Überschrift\n\n[1]\n\nEin belegter Satz [1].", {1})
    assert text == "Ein belegter Satz [1]." and dropped == 0


def test_a_marker_after_the_period_cites_the_preceding_unmarked_sentences() -> None:
    """Models often cite per paragraph ("Satz. Satz. [2]"); measured with gpt-5.6-luna on 2026-09-18."""
    text, dropped = verify_citations("Satz eins. Satz zwei. Satz drei. [2]\n\nSatz vier. [1]", {1, 2})
    assert text == "Satz eins [2]. Satz zwei [2]. Satz drei [2].\n\nSatz vier [1]."
    assert dropped == 0


def test_a_trailing_marker_stops_at_a_sentence_with_its_own_marker() -> None:
    text, dropped = verify_citations(
        "Erster Satz [1]. Zweiter Satz. Dritter Satz. [2][1] Vierter Satz ohne Beleg.", {1, 2}
    )
    assert text == "Erster Satz [1]. Zweiter Satz [2][1]. Dritter Satz [2][1]."
    assert dropped == 1


def test_an_invalid_trailing_marker_supports_nothing() -> None:
    text, dropped = verify_citations("Erster Satz. Zweiter Satz. [9]", {1})
    assert text == "" and dropped == 2


EVIDENCE = {
    1: "Licht breitet sich geradlinig aus und wird an Grenzflächen zwischen zwei Medien gebrochen.",
    2: "Im 17. Jahrhundert begann die Entwicklung der Fernrohre durch Linsenschleifer in den Niederlanden.",
}


def test_drop_unsupported_removes_sentences_the_cited_evidence_does_not_cover() -> None:
    """Measured 2026-09-18: inference sentences carry a marker although the cited chunk does not say so."""
    text = (
        "Licht breitet sich geradlinig aus und wird an Grenzflächen gebrochen [1]. "
        "Damit verweist das Thema auf allgemeine Fragen der Systemgestaltung und der Kooperation von Teilstrukturen [1]."
        "\n\nDie Entwicklung der Fernrohre begann im 17. Jahrhundert in den Niederlanden [2]."
    )
    kept, unsupported = drop_unsupported(text, EVIDENCE)
    assert kept == (
        "Licht breitet sich geradlinig aus und wird an Grenzflächen gebrochen [1]."
        "\n\nDie Entwicklung der Fernrohre begann im 17. Jahrhundert in den Niederlanden [2]."
    )
    assert unsupported == 1


def test_drop_unsupported_uses_all_cited_chunks_and_keeps_short_sentences() -> None:
    text = "Fernrohre nutzen die Brechung des Lichts an Grenzflächen [1][2]. Das gilt auch hier [2]."
    assert drop_unsupported(text, EVIDENCE) == (text, 0)


def test_drop_unsupported_removes_emptied_paragraphs() -> None:
    text = "Gesellschaftliche Debatten prägen die politische Bewertung wirtschaftlicher Interessen [1].\n\nLicht wird gebrochen [1]."
    assert drop_unsupported(text, EVIDENCE) == ("Licht wird gebrochen [1].", 1)


def test_multi_number_markers_are_expanded_into_single_markers() -> None:
    """``[1, 2]`` left as text would survive the renumbering and point at another section's sources."""
    answer = "Licht breitet sich aus [1, 2]. Linsen bündeln es [1-2]. Spiegel lenken es um [1; 2]. Prismen zerlegen es [1–2]."
    text, dropped = verify_citations(answer, {1, 2})
    assert text == (
        "Licht breitet sich aus [1][2]. Linsen bündeln es [1][2]. Spiegel lenken es um [1][2]. Prismen zerlegen es [1][2]."
    )
    assert dropped == 0
    assert verify_citations("Nur ein gültiger Beleg [2, 7].", {1, 2}) == ("Nur ein gültiger Beleg [2].", 0)
    assert verify_citations("Ein absurd großer Bereich [1-400].", {1, 2}) == ("", 1)


def test_an_uncited_quotation_does_not_ride_along_with_the_next_sentence() -> None:
    text, dropped = verify_citations("„Frei erfunden.“ Dann kam die Erfindung des Fernrohrs [1].", {1})
    assert text == "Dann kam die Erfindung des Fernrohrs [1]." and dropped == 1


def test_an_uncited_sentence_does_not_ride_along_with_a_lower_case_neighbour() -> None:
    """``split_sentences`` only splits before capitals; an uncited sentence next to a lower-case start slipped through."""
    before, dropped = verify_citations(
        "Das ist frei erfunden und ohne jeden Beleg. dann kam die Erfindung des Fernrohrs [1].", {1}
    )
    assert before == "dann kam die Erfindung des Fernrohrs [1]." and dropped == 1
    after, dropped = verify_citations(
        "Licht breitet sich geradlinig aus [1]. dann folgt ein unbelegter Rest ohne Nummer.", {1}
    )
    assert after == "Licht breitet sich geradlinig aus [1]." and dropped == 1


def test_abbreviations_before_a_lower_case_word_never_split_a_sentence() -> None:
    for answer in (
        "Dazu zählen bspw. Linsen und Spiegel [1].",
        "Dazu zählen Linsen, Spiegel usw. und weitere Geräte [1].",
        "Die Temperatur stieg um ca. anderthalb Grad [1].",
        "Das gilt einschl. der Spiegel und insbes. der Linsen [1].",
        "Das betrifft österr. und schweiz. Lehrpläne gleichermaßen [1].",
    ):
        assert verify_citations(answer, {1}) == (answer, 0), answer


def test_list_lines_are_separate_claims() -> None:
    answer = "- Punkt A ohne Beleg\n- Punkt B mit Beleg [1].\n* Punkt C mit Beleg [2]\n1. Punkt D ohne Beleg"
    text, dropped = verify_citations(answer, {1, 2})
    assert text == "Punkt B mit Beleg [1]. Punkt C mit Beleg [2]" and dropped == 2


def test_a_marker_after_an_ellipsis_belongs_to_the_sentence_before_it() -> None:
    text, dropped = verify_citations("Die Reihe setzt sich fort… [1] Der Rest ist unbelegt.", {1})
    assert text == "Die Reihe setzt sich fort [1]…" and dropped == 1


def test_a_marker_after_an_abbreviation_inside_a_sentence_stays_where_it_is() -> None:
    answer = "Dazu zählen Linsen, Spiegel usw. [1] und weitere optische Geräte [2]."
    assert verify_citations(answer, {1, 2}) == (answer, 0)


def test_shift_citations_moves_text_markers_and_citation_numbers_together() -> None:
    fake = FakeBApi(lambda body: ANSWER)
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    local = LlmSynthesizer(_client(fake)).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget
    )
    assert isinstance(local, LlmSection) and local.text == "Erster Satz [1]. Vierter Satz [2].\n\nFünfter Satz [1]."
    shifted = shift_citations(local, 7)
    assert shifted.text == "Erster Satz [8]. Vierter Satz [9].\n\nFünfter Satz [8]."
    assert [(c.number, c.chunk_id) for c in shifted.citations] == [(8, "c0"), (9, "c1")]
    assert shift_citations(local, 0) is local


def test_renumber_maps_local_to_global_numbers() -> None:
    assert renumber("A [1]. B [2] [1].", {1: 6, 2: 7}) == "A [6]. B [7] [6]."


def test_write_section_returns_verified_text_with_global_citations() -> None:
    fake = FakeBApi(lambda body: ANSWER)
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = LlmSynthesizer(_client(fake)).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=5, budget=budget
    )
    assert isinstance(result, LlmSection)
    assert result.text == "Erster Satz [6]. Vierter Satz [7].\n\nFünfter Satz [6]."
    assert [(c.number, c.chunk_id) for c in result.citations] == [(6, "c0"), (7, "c1")]
    assert result.citations[0].source_title == "Test" and result.citations[0].snippet.startswith("Das Thema ist")
    assert result.prompt == get_prompt("section_synthesis").tag and result.model == "gpt-5.6-luna"
    assert result.total_tokens == 24 and result.dropped_sentences == 2 and result.unsupported_sentences == 0
    assert budget.used == 24
    body = fake.bodies[0]
    assert 200 + REASONING_ALLOWANCE <= body["max_completion_tokens"] <= 1500 + REASONING_ALLOWANCE
    user = body["messages"][1]["content"]
    assert "Thema" in user and "Themendefinition" in user and "[2] (Test › Geschichte)" in user


def test_write_section_skips_when_the_budget_is_exhausted() -> None:
    fake = FakeBApi(lambda body: ANSWER)
    budget = TokenBudget(per_request=50, daily=2_000_000).open_request()
    result = LlmSynthesizer(_client(fake)).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget
    )
    assert isinstance(result, LlmSkipped) and "Budget" in result.reason
    assert fake.requests == []


def test_write_section_skips_on_an_api_error() -> None:
    fake = FakeBApi(statuses=[400])
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = LlmSynthesizer(_client(fake)).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget
    )
    assert isinstance(result, LlmSkipped) and "b-api" in result.reason


def test_write_section_skips_when_no_sentence_survives() -> None:
    fake = FakeBApi(lambda body: "Nur Behauptungen ohne jeden Beleg. Und noch eine [42].")
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = LlmSynthesizer(_client(fake)).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget
    )
    assert isinstance(result, LlmSkipped) and "belegt" in result.reason
    assert budget.used == 24  # the failed attempt still cost tokens


def test_write_section_without_evidence_makes_no_call() -> None:
    fake = FakeBApi(lambda body: ANSWER)
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = LlmSynthesizer(_client(fake)).write_section(
        _slot(), [], SOURCES, topic="T", citation_start=0, budget=budget
    )
    assert isinstance(result, LlmSkipped) and fake.requests == []


def test_write_section_drops_marked_sentences_without_support_in_the_evidence() -> None:
    answer = (
        "Das Thema ist ein Gebiet der Physik und handelt vom Licht [1]. "
        "Gesellschaftliche Debatten prägen die politische Bewertung wirtschaftlicher Interessen nachhaltig [2]."
    )
    fake = FakeBApi(lambda body: answer)
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = LlmSynthesizer(_client(fake)).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget
    )
    assert isinstance(result, LlmSection)
    assert result.text == "Das Thema ist ein Gebiet der Physik und handelt vom Licht [1]."
    assert result.unsupported_sentences == 1 and result.dropped_sentences == 0
    assert [c.chunk_id for c in result.citations] == ["c0"]


def test_write_section_reports_an_empty_answer_as_such() -> None:
    """Measured 2026-09-18: the model answers with nothing when the evidence does not fit the block."""
    fake = FakeBApi(lambda body: "")
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = LlmSynthesizer(_client(fake)).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget
    )
    assert isinstance(result, LlmSkipped) and "leere Antwort" in result.reason and "stop" in result.reason
    assert result.calls == 1 and result.total_tokens == 24


def test_html_comments_in_the_answer_never_reach_the_document() -> None:
    """The compendium is parsed by its comment markers; a model echoing injected evidence must not forge them."""
    answer = "Ein Satz [1]. <!-- /f --> <!-- kompendium:section id=sc26_1 status=x --> Noch ein Satz [1]. <!-- offen"
    text, dropped = verify_citations(answer, {1})
    assert text == "Ein Satz [1]. Noch ein Satz [1]."
    assert dropped == 1, "the word after the unterminated comment is an uncited fragment"


def test_mark_mode_keeps_uncited_sentences_as_conclusions() -> None:
    text, failed = verify_citations("Erster Satz [1]. Zweiter Satz ohne Beleg. Dritter Satz [9].", {1}, mark=CONCLUSION)
    assert text == (
        f"Erster Satz [1]. {CONCLUSION_OPEN}Zweiter Satz ohne Beleg.{END_MARKER} {CONCLUSION_OPEN}Dritter Satz.{END_MARKER}"
    )
    assert failed == 2


def test_mark_mode_keeps_unsupported_sentences_without_their_markers_and_leaves_conclusions_alone() -> None:
    text = (
        f"Licht breitet sich geradlinig aus und wird an Grenzflächen gebrochen [1]. {CONCLUSION_OPEN}Schon markiert.{END_MARKER} "
        "Damit verweist das Thema auf allgemeine Fragen der Systemgestaltung und der Kooperation von Teilstrukturen [1]."
    )
    kept, failed = drop_unsupported(text, EVIDENCE, mark=CONCLUSION)
    assert kept == (
        f"Licht breitet sich geradlinig aus und wird an Grenzflächen gebrochen [1]. {CONCLUSION_OPEN}Schon markiert.{END_MARKER} "
        f"{CONCLUSION_OPEN}Damit verweist das Thema auf allgemeine Fragen der Systemgestaltung und der Kooperation "
        f"von Teilstrukturen.{END_MARKER}"
    )
    assert failed == 1


def test_write_section_in_mark_mode_reports_conclusions_and_needs_one_cited_sentence() -> None:
    answer = (
        "Das Thema ist ein Gebiet der Physik und handelt vom Licht [1]. Das ist eine Folgerung ohne Beleg. "
        "Gesellschaftliche Debatten prägen die politische Bewertung wirtschaftlicher Interessen nachhaltig [2]."
    )
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    synthesizer = LlmSynthesizer(_client(FakeBApi(lambda body: answer)), mark_unsupported=True)
    result = synthesizer.write_section(_slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget)
    assert isinstance(result, LlmSection)
    assert result.text.startswith("Das Thema ist ein Gebiet der Physik und handelt vom Licht [1]. " + CONCLUSION_OPEN)
    assert result.text.count(CONCLUSION_OPEN) == 2 and result.text.count(END_MARKER) == 2 and "[2]" not in result.text
    assert (result.dropped_sentences, result.unsupported_sentences, result.marked_sentences) == (1, 1, 2)
    assert [c.chunk_id for c in result.citations] == ["c0"]

    only_conclusions = LlmSynthesizer(_client(FakeBApi(lambda body: "Nur eine Folgerung.")), mark_unsupported=True)
    skipped = only_conclusions.write_section(_slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget)
    assert isinstance(skipped, LlmSkipped) and "belegt" in skipped.reason


def test_removing_invalid_numbers_never_reassembles_a_comment_delimiter() -> None:
    """``-[9]->`` turns into ``-->`` once the invalid number is gone; the same for ``<!-[9]-``."""
    for mark in ("", CONCLUSION, MODEL_KNOWLEDGE):
        text, _ = verify_citations(
            "Ein Pfeil -[9]-> zeigt nach rechts [1]. Offen <!-[9]- und ohne Beleg.", {1}, mark=mark
        )
        body = text.replace(opening_marker(mark), "").replace(END_MARKER, "")
        assert "-->" not in body and "<!--" not in body, text
    unsupported = "Gesellschaftliche Debatten prägen -[1]-> die politische Bewertung wirtschaftlicher Interessen."
    text, failed = drop_unsupported(unsupported, EVIDENCE, mark=CONCLUSION)
    assert failed == 1 and "-->" not in text.replace(CONCLUSION_OPEN, "").replace(END_MARKER, "")


def test_an_ellipsis_or_a_scholarly_abbreviation_before_a_lower_case_word_is_no_sentence_end() -> None:
    for answer in (
        "Die Entwicklung beschleunigte sich weiter… und endet bis heute nicht [1].",
        "Der sogen. schwarze Körper absorbiert das gesamte Licht [1].",
        "Das gilt ausschl. für sichtbares Licht und entspr. für Infrarot [1].",
    ):
        assert verify_citations(answer, {1}) == (answer, 0), answer


def test_enrichment_marks_model_knowledge_instead_of_dropping_it() -> None:
    """enrichment=model-knowledge (docs/umbau.md U4): a sentence beyond the evidence stays, graded Modellwissen."""
    answer = (
        "Das Thema ist ein Gebiet der Physik und handelt vom Licht [1]. "
        "Linsen bündeln Licht, weil sie es an ihren Grenzflächen brechen."
    )
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    synthesizer = LlmSynthesizer(_client(FakeBApi(lambda body: answer)))
    result = synthesizer.write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget, enrich=True
    )
    assert isinstance(result, LlmSection)
    assert MODEL_KNOWLEDGE_OPEN in result.text and CONCLUSION_OPEN not in result.text
    assert result.marked_sentences == 1 and result.prompt == get_prompt("section_enrichment").tag


def test_model_knowledge_is_marked_visibly_inside_its_block_and_a_conclusion_is_not() -> None:
    """D56 (Jan): a reader of the rendered text sees which sentence no source covers - the comment alone hid it.

    The label stands inside the marked block, so whatever parses the blocks keeps the sentence and its label
    together. A conclusion (LLM_UNSUPPORTED_SENTENCES=mark) stays as it was: nobody asked for it to show.
    """
    answer = "Licht breitet sich geradlinig aus [1]. Linsen bündeln Licht an ihren Grenzflächen."
    for marked, failed in (
        verify_citations(answer, {1}, mark=MODEL_KNOWLEDGE),
        drop_unsupported(
            "Gesellschaftliche Debatten prägen die politische Bewertung [1].", EVIDENCE, mark=MODEL_KNOWLEDGE
        ),
    ):
        assert failed == 1 and f" {MODEL_KNOWLEDGE_LABEL}{END_MARKER}" in marked, marked
    concluded, _ = verify_citations(answer, {1}, mark=CONCLUSION)
    assert CONCLUSION_OPEN in concluded and MODEL_KNOWLEDGE_LABEL not in concluded


def test_a_sentence_the_model_labels_itself_keeps_one_label() -> None:
    """M31: one sentence in 50 came back as "Modellwissen: In Zellstoffwerken wird Holz …" - with the label the
    service adds, it read "Modellwissen: … [Modellwissen]"."""
    answer = "Licht breitet sich geradlinig aus [1]. Modellwissen: Linsen bündeln Licht an ihren Grenzflächen."
    text, failed = verify_citations(answer, {1}, mark=MODEL_KNOWLEDGE)
    assert failed == 1
    assert (
        f"{MODEL_KNOWLEDGE_OPEN}Linsen bündeln Licht an ihren Grenzflächen. {MODEL_KNOWLEDGE_LABEL}{END_MARKER}" in text
    )


def test_the_enrichment_prompt_asks_for_facts_and_forbids_the_fillers_of_m28() -> None:
    """D56: two judges called two thirds of the model knowledge of v1 fillers (M28) - sentences about the block,
    the compendium or the lesson, and transfer phrases. v2 asks for a checkable fact or nothing."""
    prompt = get_prompt("section_enrichment")
    assert prompt.version == 2
    for rule in (
        "überprüfbare Sachaussage",
        "Baustein, das Kompendium, den Unterricht",
        "Transferprinzip",
        "ergänze nichts",
    ):
        assert rule in prompt.system, rule


def test_without_enrichment_the_same_answer_loses_the_unsupported_sentence() -> None:
    answer = (
        "Das Thema ist ein Gebiet der Physik und handelt vom Licht [1]. "
        "Linsen bündeln Licht, weil sie es an ihren Grenzflächen brechen."
    )
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    result = LlmSynthesizer(_client(FakeBApi(lambda body: answer))).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget
    )
    assert isinstance(result, LlmSection)
    assert "Linsen" not in result.text and result.marked_sentences == 0
    assert result.prompt == get_prompt("section_synthesis").tag


def test_enrichment_still_needs_one_sentence_from_the_sources() -> None:
    """A block made only of model knowledge is no compendium block; the extractive text takes over."""
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
    synthesizer = LlmSynthesizer(_client(FakeBApi(lambda body: "Alles nur aus dem Modellwissen geschöpft.")))
    result = synthesizer.write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=0, budget=budget, enrich=True
    )
    assert isinstance(result, LlmSkipped) and "belegt" in result.reason


def test_a_reading_text_carries_no_evidence_numbers() -> None:
    """The markers belong to the compendium, not to a text something else is built from.

    Every sentence of part 1 ends with at least one evidence number, and they sit inside the block text
    rather than in the markdown around it. A question generator reads them as words: measured on the
    running service on 2026-09-21 one pair came back as "Woraus besteht [12] Das Arbeitsfeld eines
    Optotechnikers?".
    """
    assert without_markers("Licht breitet sich geradlinig aus [2].") == "Licht breitet sich geradlinig aus."
    assert (
        without_markers("Er maß die Brechung. [12]\nDas Feld ist weit.") == "Er maß die Brechung.\nDas Feld ist weit."
    )
    assert without_markers("Beides gilt [1, 2] und mehr [3; 4].") == "Beides gilt und mehr."
    assert without_markers("Ohne Nummern bleibt alles.") == "Ohne Nummern bleibt alles."
    assert without_markers(f"Linsen bündeln Licht. {MODEL_KNOWLEDGE_LABEL} Mehr.") == "Linsen bündeln Licht. Mehr."
