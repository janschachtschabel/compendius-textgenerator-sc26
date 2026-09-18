"""Gold standard files: text hashes, JSONL round trip, CSV export and import for manual labelling."""

import csv
from pathlib import Path

import pytest

from app.domain.models import Chunk
from app.matching.gold import GoldLabel, GoldSet, export_csv, import_csv, load_gold, save_gold, text_hash

SLOT_KEYS = ["themendefinition", "fachinhalte", "praxis"]


def _chunk(cid: str, heading: str, text: str) -> Chunk:
    return Chunk(chunk_id=cid, source_id="wikipedia:Test", heading=heading, heading_path=[heading], text=text)


def test_text_hash_ignores_whitespace_and_case() -> None:
    assert text_hash("Die  Optik\nist die Lehre") == text_hash("die optik ist die lehre")
    assert len(text_hash("x")) == 16
    assert text_hash("a") != text_hash("b")


def test_jsonl_round_trip_keeps_meta_and_labels(tmp_path: Path) -> None:
    gold = GoldSet(
        topic="Optik",
        labeled_by="test",
        labels=[
            GoldLabel(chunk_id="a", slot="fachinhalte", text_hash="0" * 16, heading="Grundlagen"),
            GoldLabel(chunk_id="b", slot=None, text_hash="1" * 16),
        ],
    )
    path = save_gold(tmp_path / "optik.jsonl", gold)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith('{"_meta"')
    assert len(lines) == 3
    loaded = load_gold(path)
    assert loaded.topic == "Optik"
    assert loaded.labeled_by == "test"
    assert loaded.labels == gold.labels
    assert loaded.by_hash()["1" * 16].slot is None


def test_csv_export_and_import(tmp_path: Path) -> None:
    chunks = [
        _chunk("c0", "Einleitung", "Die Optik ist die Lehre vom Licht."),
        _chunk("c1", "Geschichte", 'Im 17. Jahrhundert; Zeile mit\nUmbruch und "Anführungszeichen".'),
    ]
    path = export_csv(tmp_path / "optik.csv", chunks, suggestions={"c0": "themendefinition"})
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert [r["chunk_id"] for r in rows] == ["c0", "c1"]
    assert rows[0]["suggested_slot"] == "themendefinition"
    assert rows[1]["suggested_slot"] == ""
    assert rows[0]["gold_slot"] == ""
    assert "Umbruch" in rows[1]["text"]

    # a reviewer fills the gold column; empty means "belongs to no block"
    rows[0]["gold_slot"] = "themendefinition"
    rows[1]["gold_slot"] = ""
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    gold = import_csv(path, topic="Optik", slot_keys=SLOT_KEYS, labeled_by="test")
    assert gold.topic == "Optik"
    assert [(g.chunk_id, g.slot) for g in gold.labels] == [("c0", "themendefinition"), ("c1", None)]
    assert gold.labels[1].text_hash == text_hash(chunks[1].text)
    assert gold.labels[0].heading == "Einleitung"


def test_import_rejects_unknown_slot(tmp_path: Path) -> None:
    path = export_csv(tmp_path / "x.csv", [_chunk("c0", "H", "Text.")], suggestions={})
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    rows[0]["gold_slot"] = "foo"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="foo"):
        import_csv(path, topic="X", slot_keys=SLOT_KEYS)
