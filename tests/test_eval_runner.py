"""Eval runner on the offline sample archives: export for labelling, evaluate matchers, gold directory."""

from pathlib import Path
from typing import Any

import pytest

from app.domain.requests import GenerateRequest
from app.matching.eval_runner import evaluate_gold_dir, evaluate_topic, export_topic
from app.matching.gold import GoldLabel, GoldSet, save_gold, text_hash
from app.service import CompendiumService
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_extraction import first_sentences
from tests.test_pipeline_llm import make_gateway


def _gold_for_optik(service: CompendiumService) -> GoldSet:
    prepared = service.prepare(GenerateRequest(topic="Optik"))
    lead = next(c for c in prepared.chunks if c.is_lead)
    other = next(c for c in prepared.chunks if not c.is_lead and c.source_id == lead.source_id)
    return GoldSet(
        topic="Optik",
        labels=[
            GoldLabel(chunk_id=lead.chunk_id, slot="themendefinition", text_hash=text_hash(lead.text)),
            GoldLabel(chunk_id=other.chunk_id, slot=None, text_hash=text_hash(other.text)),
            GoldLabel(chunk_id="gone:c99", slot="praxis", text_hash="0" * 16),
        ],
    )


def test_prepare_exposes_corpus_and_chunks(service: CompendiumService) -> None:
    prepared = service.prepare(GenerateRequest(topic="Optik in Klasse 7"))
    assert prepared.resolution.title == "Optik"
    assert prepared.template.id == "sc26"
    assert len(prepared.chunks) > 10
    assert set(prepared.sources_by_id) == {s.source_id for s in prepared.sources}
    assert set(prepared.timings) == {"resolve", "corpus", "segment"}


def test_export_writes_every_chunk_with_suggestions(service: CompendiumService, tmp_path: Path) -> None:
    path, count = export_topic(service, "Optik", tmp_path / "optik.csv")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert count > 10
    assert len(lines) == count + 1  # header plus one row per chunk (texts are single lines)
    assert lines[0].startswith("chunk_id;source_id;heading;kind;suggested_slot;gold_slot;text_hash;text")
    assert any(";themendefinition;" in line for line in lines[1:])


def test_evaluate_topic_runs_several_matchers(service: CompendiumService) -> None:
    run = evaluate_topic(service, _gold_for_optik(service), matchers=["lexicon_only", "hybrid_light"])
    assert set(run.results) == {"lexicon_only", "hybrid_light"}
    result = run.results["hybrid_light"]
    assert result.topic == "Optik"
    assert result.matcher == "hybrid_light"
    assert (result.labeled, result.stale_labels) == (2, 1)
    assert {m.slot: m.tp for m in result.slots}["themendefinition"] == 1  # the lead always goes to block 1
    assert result.duration_ms >= 0
    assert run.alignment.stale[0].chunk_id == "gone:c99"


def test_compare_reports_classification_and_selection(service: CompendiumService) -> None:
    from app.matching.eval_runner import compare_topic

    gold = _gold_for_optik(service)
    compared = compare_topic(service, "Optik", ["hybrid_light"], gold=gold)
    outcome = compared.results["hybrid_light"]
    assert outcome.metrics is not None and outcome.selection is not None
    assert outcome.selection.assigned <= outcome.metrics.assigned  # budgets only remove chunks


def test_evaluate_gold_dir_skips_unknown_topics(service: CompendiumService, tmp_path: Path) -> None:
    save_gold(tmp_path / "optik.jsonl", _gold_for_optik(service))
    save_gold(tmp_path / "xyzzy.jsonl", GoldSet(topic="Xyzzyplomb", labels=[]))
    report = evaluate_gold_dir(service, tmp_path, matchers=["hybrid_light"])
    assert report.skipped == ["Xyzzyplomb"]
    assert [run.topic for run in report.runs] == ["Optik"]
    total = report.aggregate["hybrid_light"]
    assert total.topics == ["Optik"]
    assert total.labeled == 2
    assert total.stale_labels == 1


def test_the_llm_extraction_is_evaluated_as_a_strategy_of_its_own(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.matching.eval_runner import compare_topic

    fake = FakeBApi(first_sentences)
    monkeypatch.setattr(service, "llm", make_gateway(fake))
    gold = _gold_for_optik(service)
    compared = compare_topic(service, "Optik", ["hybrid_light"], gold=gold, llm_extraction=True)
    outcome = compared.results["hybrid_light+llm"]
    assert outcome.metrics is not None and outcome.metrics.matcher == "hybrid_light+llm"
    assert outcome.selection == outcome.metrics  # what the LLM chose is what the text prints
    assert {m.slot: m.tp for m in outcome.metrics.slots}["themendefinition"] == 1  # the lead's first sentence
    assert fake.bodies and outcome.metrics.llm_tokens == 24 * len(fake.bodies)
    assert compared.results["hybrid_light"].metrics is not None
    assert compared.results["hybrid_light"].metrics.llm_tokens == 0


def test_without_a_usable_llm_the_extraction_is_left_out(service: CompendiumService, tmp_path: Path) -> None:
    assert service.llm is None
    save_gold(tmp_path / "optik.jsonl", _gold_for_optik(service))
    report = evaluate_gold_dir(service, tmp_path, matchers=["hybrid_light"], llm_extraction=True)
    assert set(report.aggregate) == set(report.printed) == {"hybrid_light"}
    assert report.llm_note is not None and "konfiguriert" in report.llm_note


def test_the_gold_directory_pools_the_llm_extraction(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(first_sentences)))
    save_gold(tmp_path / "optik.jsonl", _gold_for_optik(service))
    report = evaluate_gold_dir(service, tmp_path, matchers=["hybrid_light"], llm_extraction=True)
    # The LLM's choice is only comparable with what the rules print: it has no classification before budgets
    assert set(report.aggregate) == {"hybrid_light"}
    assert set(report.printed) == {"hybrid_light", "hybrid_light+llm"}
    assert report.printed["hybrid_light+llm"].llm_tokens > 0 and report.llm_note is None
    assert report.printed["hybrid_light"].assigned <= report.aggregate["hybrid_light"].assigned
    assert set(report.runs[0].printed) == {"hybrid_light", "hybrid_light+llm"}


def test_blocks_that_fell_back_are_named_in_the_measurement(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.matching.eval_runner import compare_topic

    def one_block_fails(body: dict[str, Any]) -> str:
        user = body["messages"][1]["content"]
        return "kaputt" if "Baustein: 1 · Themendefinition" in user else first_sentences(body)

    monkeypatch.setattr(service, "llm", make_gateway(FakeBApi(one_block_fails)))
    gold = _gold_for_optik(service)
    compared = compare_topic(service, "Optik", ["hybrid_light"], gold=gold, llm_extraction=True)
    metrics = compared.results["hybrid_light+llm"].metrics
    assert metrics is not None and metrics.llm_fallbacks == 1  # that block kept the policy's paragraphs
