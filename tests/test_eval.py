"""Evaluation metrics against the gold standard (PLAN.md 4.5)."""

import pytest

from app.domain.models import Chunk, ScoredChunk
from app.matching.eval import aggregate, align, evaluate, predictions_from_assignment, predictions_from_selection
from app.matching.gold import GoldLabel, GoldSet, text_hash
from app.templates.manager import TemplateManager

SLOTS = ["themendefinition", "fachinhalte", "praxis", "bildung"]
GOLD = {"c0": "themendefinition", "c1": "fachinhalte", "c2": "fachinhalte", "c3": None, "c4": "praxis"}
PRED = {"c0": "themendefinition", "c1": "fachinhalte", "c2": "praxis", "c3": "praxis"}


def _chunk(cid: str, text: str) -> Chunk:
    return Chunk(chunk_id=cid, source_id="wikipedia:Test", heading="H", text=text)


def test_metrics_per_slot_and_macro() -> None:
    result = evaluate("Optik", GOLD, PRED, SLOTS)
    by = {m.slot: m for m in result.slots}
    assert (by["themendefinition"].precision, by["themendefinition"].recall, by["themendefinition"].f1) == (
        1.0,
        1.0,
        1.0,
    )
    assert (by["fachinhalte"].tp, by["fachinhalte"].fp, by["fachinhalte"].fn) == (1, 0, 1)
    assert (by["praxis"].tp, by["praxis"].fp, by["praxis"].fn) == (0, 2, 1)
    assert by["praxis"].f1 == 0.0
    assert by["bildung"].support == 0
    assert result.macro_f1 == pytest.approx((1.0 + 2 / 3 + 0.0) / 3, abs=1e-3)  # slots with gold support only
    assert result.micro_f1 == pytest.approx(2 * 2 / (2 * 2 + 2 + 2), abs=1e-3)  # tp=2, fp=2, fn=2
    assert (result.labeled, result.assigned, result.misassigned, result.missed) == (5, 4, 2, 1)
    assert result.hallucination_slots == []
    assert result.honest_empty_slots == ["bildung"]


def test_hallucination_slot_is_reported() -> None:
    pred = dict(PRED, c3="bildung")
    result = evaluate("Optik", GOLD, pred, SLOTS)
    assert result.hallucination_slots == ["bildung"]
    assert result.honest_empty_slots == []
    assert result.macro_f1 == pytest.approx((1.0 + 2 / 3 + 0.0) / 3, abs=1e-3)  # bildung stays out of the macro


def test_predictions_ignore_unlabeled_chunks() -> None:
    result = evaluate("Optik", GOLD, dict(PRED, c9="praxis"), SLOTS)
    assert result.assigned == 4
    assert {m.slot: m.fp for m in result.slots}["praxis"] == 2


def test_aggregate_pools_counts_over_topics() -> None:
    first = evaluate("A", GOLD, PRED, SLOTS)
    second = evaluate("B", {"d0": "praxis", "d1": "praxis"}, {"d0": "praxis", "d1": "praxis"}, SLOTS)
    total = aggregate([first, second])
    by = {m.slot: m for m in total.slots}
    assert total.topic == "gesamt"
    assert (by["praxis"].tp, by["praxis"].fp, by["praxis"].fn) == (2, 2, 1)
    assert by["praxis"].precision == pytest.approx(0.5)
    assert by["praxis"].recall == pytest.approx(2 / 3)
    assert (total.labeled, total.assigned, total.misassigned, total.missed) == (7, 6, 2, 1)
    assert total.topics == ["A", "B"]


def test_align_by_text_hash_then_chunk_id() -> None:
    chunks = [_chunk("new:c1", "Die Optik ist die Lehre vom Licht."), _chunk("new:c2", "Zweiter Absatz.")]
    gold = GoldSet(
        topic="Optik",
        labels=[
            GoldLabel(
                chunk_id="old:c7", slot="themendefinition", text_hash=text_hash("die optik ist die lehre vom licht.")
            ),
            GoldLabel(chunk_id="new:c2", slot=None, text_hash="f" * 16),  # text changed, id still valid
            GoldLabel(chunk_id="old:c9", slot="praxis", text_hash="e" * 16),  # gone
        ],
    )
    alignment = align(gold, chunks)
    assert alignment.gold_by_chunk == {"new:c1": "themendefinition", "new:c2": None}
    assert [label.chunk_id for label in alignment.stale] == ["old:c9"]
    assert alignment.matched_by_id == 1


def test_predictions_from_assignment_maps_slot_ids_to_keys() -> None:
    template = TemplateManager().get("sc26")
    chunk = _chunk("c0", "Text.")
    assigned = {"sc26_3": [ScoredChunk(chunk=chunk, score=1.0)], "sc26_10": []}
    assert predictions_from_assignment(assigned, template) == {"c0": "fachinhalte"}


def test_a_paragraph_the_llm_split_counts_for_the_block_with_most_of_its_sentences() -> None:
    template = TemplateManager().get("sc26")
    both = _chunk("c0", "Licht breitet sich geradlinig aus. Es wird an Spiegeln reflektiert.")
    first = _chunk("c0", "Licht breitet sich geradlinig aus.")
    other = _chunk("c1", "Brillen korrigieren Fehlsichtigkeit.")
    assigned = {  # dict order is not template order: the tie below must still go to the earlier block
        "sc26_10": [ScoredChunk(chunk=other, score=1.0)],
        "sc26_1": [ScoredChunk(chunk=first, score=1.0)],
        "sc26_3": [ScoredChunk(chunk=both, score=1.0), ScoredChunk(chunk=other, score=1.0)],
    }
    assert predictions_from_selection(assigned, template) == {"c0": "fachinhalte", "c1": "fachinhalte"}


def test_confusion_lists_mismatches_and_is_pooled() -> None:
    result = evaluate("Optik", GOLD, PRED, SLOTS)
    assert result.confusion == {"fachinhalte>praxis": 1, "none>praxis": 1}
    total = aggregate([result, result])
    assert total.confusion == {"fachinhalte>praxis": 2, "none>praxis": 2}


def test_alignment_never_reuses_a_label_after_a_position_shift() -> None:
    # Labels were made when "eins" sat at c001 and "zwei" at c002; a dropped paragraph moved both up.
    chunks = [_chunk("a:c000", "Absatz eins."), _chunk("a:c001", "Absatz zwei."), _chunk("a:c002", "Neuer Absatz.")]
    gold = GoldSet(
        topic="A",
        labels=[
            GoldLabel(chunk_id="a:c001", slot="praxis", text_hash=text_hash("Absatz eins.")),
            GoldLabel(chunk_id="a:c002", slot="bildung", text_hash=text_hash("Absatz zwei.")),
        ],
    )
    alignment = align(gold, chunks)
    assert alignment.gold_by_chunk == {"a:c000": "praxis", "a:c001": "bildung"}
    assert alignment.matched_by_id == 0
    assert alignment.stale == []
