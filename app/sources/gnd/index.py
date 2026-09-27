"""The local GND index (D65): GND records an article without a Normdaten block can get, from the DNB's dumps.

The German Wikipedia names the GND record of most articles in their Normdaten block (M18, M41); a quarter of the
correct articles have none (M41). The DNB publishes its authority records as dumps (data.dnb.de/opendata, CC0,
Turtle). ``build_gnd_index`` streams them into one SQLite file: which record names a Wikidata item (``owl:sameAs``) and
which record carries a name, preferred or variant. It keeps only what leads to exactly one record - an item or a name
two records share proves nothing. ``GndIndex.find`` asks the item of the article first, then its title, the Wikipedia
qualifier "Folge (Mathematik)" also as the GND writes it, "Folge <Mathematik>". Measured on the correct articles of
M36 (M42): where the Normdaten block names the GND, the item led to the same record in 104 of 106 cases and the name in
88 of 89; of the 49 without one, 22 got a proposal, 21 of them right after two blind raters.

Only the subject headings (Sachbegriffe) and the places (Geografika) go in: every proposal of M42 for the gap came from
the subject headings, while the corporate bodies (205 MB, 1.6 million names) brought none and many namesakes.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.sources.local_index import LocalIndex, write_atomically

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
# Turtle strings escape quotes and backslashes with a backslash; it is spelled chr(92) to keep the patterns readable.
BACKSLASH = chr(92)
_SUBJECT_RE = re.compile(r"^<https://d-nb\.info/gnd/([0-9X-]+)>\s+(.*)$")
_STRING_RE = re.compile('"((?:[^"' + BACKSLASH * 2 + "]|" + BACKSLASH * 2 + '.)*)"')
_ESCAPE_RE = re.compile(BACKSLASH * 2 + "(.)")
_WIKIDATA_RE = re.compile(r"<http://www\.wikidata\.org/entity/(Q\d+)>")
_VERSION_RE = re.compile(r"_(\d{4})(\d{2})(\d{2})\.ttl\.gz$")
NAME_PREDICATES = ("gndo:preferredNameFor", "gndo:variantNameFor")


@dataclass(frozen=True)
class GndHit:
    number: str
    kind: str  # "Sachbegriff" or "Geografikum": the dump the record came from
    source: str  # "wikidata": the record names the article's item; "name": the one record with the article's title


def _pairs(path: Path) -> Iterator[tuple[str, str | None, str | None]]:
    """(GND number, name, item) for every record of a dump, read line by line; a record's blocks may be apart."""
    number: str | None = None
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("<"):
                subject = _SUBJECT_RE.match(line)  # an ".../about>" block describes the record, it is none
                if subject is None:
                    number = None
                    continue
                number = subject.group(1)
                yield number, None, None
                rest = subject.group(2)
            elif number is not None and line.startswith("  "):
                rest = line.strip()
            else:
                continue
            predicate, _, objects = rest.partition(" ")
            if predicate.startswith(NAME_PREDICATES):
                for name in _STRING_RE.findall(objects):
                    yield number, _ESCAPE_RE.sub(r"\1", name), None
            elif predicate == "owl:sameAs":
                for item in _WIKIDATA_RE.findall(objects):
                    yield number, None, item


def _release(paths: Sequence[Path]) -> str | None:
    """The DNB's version of the dumps, from their names (``…_lds_20260217.ttl.gz``); ``None`` for undated names."""
    versions = {match.groups() for path in paths if (match := _VERSION_RE.search(path.name))}
    return "-".join(versions.pop()) if len(versions) == 1 else None


def _write(target: Path, dumps: Sequence[tuple[Path, str]]) -> dict[str, Any]:
    connection = sqlite3.connect(target)
    try:
        connection.executescript(
            "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
            "CREATE TABLE records (gnd TEXT PRIMARY KEY, kind TEXT NOT NULL) WITHOUT ROWID;"
            "CREATE TABLE item_pairs (qid TEXT NOT NULL, gnd TEXT NOT NULL);"
            "CREATE TABLE name_pairs (name TEXT NOT NULL, gnd TEXT NOT NULL);"
        )
        for path, kind in dumps:
            for number, name, item in _pairs(path):
                if name is not None:
                    connection.execute("INSERT INTO name_pairs VALUES (?, ?)", (name.strip().casefold(), number))
                elif item is not None:
                    connection.execute("INSERT INTO item_pairs VALUES (?, ?)", (item, number))
                else:
                    connection.execute("INSERT OR IGNORE INTO records VALUES (?, ?)", (number, kind))
        connection.executescript(
            # What leads to exactly one record; a name or an item two records share proves nothing
            "CREATE TABLE items (qid TEXT PRIMARY KEY, gnd TEXT NOT NULL) WITHOUT ROWID;"
            "INSERT INTO items SELECT qid, MIN(gnd) FROM item_pairs GROUP BY qid HAVING COUNT(DISTINCT gnd) = 1;"
            "CREATE TABLE names (name TEXT PRIMARY KEY, gnd TEXT NOT NULL) WITHOUT ROWID;"
            "INSERT INTO names SELECT name, MIN(gnd) FROM name_pairs WHERE name != ''"
            " GROUP BY name HAVING COUNT(DISTINCT gnd) = 1;"
            "DROP TABLE item_pairs; DROP TABLE name_pairs;"
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 - own names
                  for table in ("records", "items", "names")}  # fmt: skip
        if not counts["records"]:  # a layout the reader does not know must not end as an index that answers nothing
            raise ValueError(f"no GND record in {', '.join(path.name for path, _ in dumps)}")
        meta = {
            "schema": SCHEMA_VERSION,
            **{key: str(value) for key, value in counts.items()},
            "release": _release([path for path, _ in dumps]) or "",
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "sources": json.dumps([path.name for path, _ in dumps]),
        }
        connection.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    return _read_meta(meta)


def build_gnd_index(dumps: Sequence[tuple[Path, str]], target: Path) -> dict[str, Any]:
    """Build the index from ``(dump, kind)`` pairs; an index already at ``target`` stays until the new one is done."""
    dumps = [(Path(path), kind) for path, kind in dumps]
    for path, _ in dumps:
        if not path.is_file():
            raise FileNotFoundError(f"dump not found: {path}")
    meta = write_atomically(Path(target), lambda partial: _write(partial, dumps))
    log.info("GND index %s: %d records of the release %s", target, meta["records"], meta["release"] or "?")
    return meta


def _read_meta(rows: dict[str, str]) -> dict[str, Any]:
    return {
        "records": int(rows.get("records", "0")),
        "items": int(rows.get("items", "0")),
        "names": int(rows.get("names", "0")),
        "release": rows.get("release") or None,
        "built_at": rows.get("built_at"),
        "sources": json.loads(rows.get("sources", "[]")),
    }


def _names(title: str) -> list[tuple[str]]:
    """A Wikipedia title as the index keeps names, and "Folge (Mathematik)" also as the GND's "Folge <Mathematik>"."""
    name = title.replace("_", " ").strip()
    forms = [name]
    if (match := re.fullmatch(r"(.+?) \((.+)\)", name)) is not None:
        forms.append(f"{match.group(1)} <{match.group(2)}>")
    return [(form.casefold(),) for form in forms if form]


class GndIndex(LocalIndex):
    """Read-only lookups in the index; a missing or foreign file answers nothing instead of failing."""

    label = "GND index"
    schema = SCHEMA_VERSION

    def read_meta(self, rows: dict[str, str]) -> dict[str, Any]:
        return _read_meta(rows)

    def find(self, title: str, qid: str | None) -> GndHit | None:
        """The GND record of the article ``title`` with the Wikidata item ``qid``: the record that names the item,
        else the one record that carries the title as a name; ``None`` when nothing leads to exactly one."""
        if qid:
            row = self._first(
                "SELECT items.gnd, records.kind FROM items JOIN records USING (gnd) WHERE items.qid = ?", [(qid,)]
            )
            if row:
                return GndHit(str(row[0]), str(row[1]), "wikidata")
        row = self._first(
            "SELECT names.gnd, records.kind FROM names JOIN records USING (gnd) WHERE names.name = ?", _names(title)
        )
        return GndHit(str(row[0]), str(row[1]), "name") if row else None
