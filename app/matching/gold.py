"""Gold standard for slot matching (PLAN.md 4.5): labels per chunk, JSONL storage, CSV for reviewers.

A label points to a chunk by the hash of its normalised text, so labels survive changes in
chunk numbering; the chunk id stays as fallback and for readability. Reviewers work on a CSV
(semicolon separated, Excel friendly) and fill the ``gold_slot`` column with a slot key, ``none``
or nothing for "belongs to no block".
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import Chunk

GOLD_NONE = "none"
CSV_DELIMITER = ";"
CSV_COLUMNS = ["chunk_id", "source_id", "heading", "kind", "suggested_slot", "gold_slot", "text_hash", "text"]
TEXT_HEAD_CHARS = 80


def text_hash(text: str) -> str:
    """Stable 16-hex fingerprint of a text, ignoring case and whitespace differences."""
    normalised = " ".join(text.lower().split())
    return hashlib.sha1(normalised.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


class GoldLabel(BaseModel):
    chunk_id: str
    slot: str | None = Field(None, description="Slot key; None when the chunk belongs to no block")
    text_hash: str
    heading: str = ""
    text_head: str = ""


class GoldSet(BaseModel):
    topic: str
    template_id: str = "sc26"
    created_at: str = ""
    labeled_by: str = ""
    zim: list[dict[str, Any]] = Field(default_factory=list, description="Archive snapshot the labels were made on")
    labels: list[GoldLabel] = Field(default_factory=list)

    def by_hash(self) -> dict[str, GoldLabel]:
        return {label.text_hash: label for label in self.labels}

    def by_id(self) -> dict[str, GoldLabel]:
        return {label.chunk_id: label for label in self.labels}


def load_gold(path: Path) -> GoldSet:
    """Read a JSONL gold file: an optional first ``{"_meta": …}`` line, then one label per line."""
    meta: dict[str, Any] = {}
    labels: list[GoldLabel] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if "_meta" in record:
            meta = dict(record["_meta"])
            continue
        if record.get("slot") == GOLD_NONE:
            record["slot"] = None
        labels.append(GoldLabel.model_validate(record))
    meta.setdefault("topic", Path(path).stem)
    return GoldSet(**meta, labels=labels)


def save_gold(path: Path, gold: GoldSet) -> Path:
    meta = gold.model_dump(exclude={"labels"})
    lines = [json.dumps({"_meta": meta}, ensure_ascii=False)]
    for label in gold.labels:
        record = label.model_dump()
        record["slot"] = label.slot or GOLD_NONE
        lines.append(json.dumps(record, ensure_ascii=False))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def export_csv(path: Path, chunks: Sequence[Chunk], suggestions: Mapping[str, str]) -> Path:
    """Write chunks for review; ``suggested_slot`` is the current prediction, ``gold_slot`` stays empty."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=CSV_DELIMITER)
        writer.writerow(CSV_COLUMNS)
        for chunk in chunks:
            writer.writerow(
                [
                    chunk.chunk_id,
                    chunk.source_id,
                    chunk.full_heading,
                    chunk.kind.value,
                    suggestions.get(chunk.chunk_id, ""),
                    "",
                    text_hash(chunk.text),
                    _one_line(chunk.text),
                ]
            )
    return target


def import_csv(path: Path, topic: str, slot_keys: Sequence[str], **meta: Any) -> GoldSet:
    """Turn a reviewed CSV into a gold set; ``gold_slot`` must be a slot key, ``none`` or empty."""
    allowed = set(slot_keys)
    labels: list[GoldLabel] = []
    offenders: list[str] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=CSV_DELIMITER):
            raw_slot = (row.get("gold_slot") or "").strip()
            slot = None if raw_slot in ("", GOLD_NONE) else raw_slot
            if slot is not None and slot not in allowed:
                offenders.append(f"{row.get('chunk_id')}: {slot!r}")
                continue
            text = row.get("text") or ""
            labels.append(
                GoldLabel(
                    chunk_id=row["chunk_id"],
                    slot=slot,
                    text_hash=row.get("text_hash") or text_hash(text),
                    heading=row.get("heading", ""),
                    text_head=text[:TEXT_HEAD_CHARS],
                )
            )
    if offenders:
        raise ValueError("unknown slot key(s) in gold_slot: " + "; ".join(offenders))
    created_at = meta.pop("created_at", "") or datetime.now(UTC).replace(microsecond=0).isoformat()
    return GoldSet(topic=topic, created_at=created_at, labels=labels, **meta)
