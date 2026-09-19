"""SQLite cache of harvested curricula (PLAN.md 5.2, 5.3): written whole by the harvest, read locally.

The harvest writes a new file next to the old one and swaps it in with ``os.replace``; readers open a
connection per call, so an API process picks up the swapped file without a restart. Search uses an
FTS5 trigram index over node and parent labels: substring and case-insensitive, which German
compounds need (a topic word at the end of a compound); the word-boundary noise rule is applied by
the matcher.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.sources.lehrplan.tree import HarvestedNode
from app.sources.lehrplan.vocab import MATCHABLE_ROLES

log = logging.getLogger(__name__)

# Bump when the tables change; a cache written by another version counts as unreadable (part 2 renders
# its hint) instead of failing every compendium request.
SCHEMA_VERSION = "1"
TMP_SUFFIX = ".tmp"
MIN_KEYWORD_CHARS = 3  # the trigram tokenizer cannot match anything shorter
# Broad keywords without a subject filter hit thousands of nodes; ranking happens after the fetch,
# so the fetch must not cut them off in insertion order.
DEFAULT_SEARCH_LIMIT = 20_000
_REPLACE_ATTEMPTS = 5

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE lehrplan (
    iri TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    bundesland_code TEXT NOT NULL,
    bundesland TEXT NOT NULL,
    schularten TEXT NOT NULL,
    schulfaecher TEXT NOT NULL,
    schulfaecher_lc TEXT NOT NULL,
    jahrgangsstufen TEXT NOT NULL,
    schulstufen TEXT NOT NULL
);
CREATE TABLE node (
    id INTEGER PRIMARY KEY,
    iri TEXT NOT NULL,
    lehrplan_iri TEXT NOT NULL REFERENCES lehrplan(iri),
    label TEXT NOT NULL,
    parent_iri TEXT,
    parent_label TEXT NOT NULL,
    rollen TEXT NOT NULL,
    matchable INTEGER NOT NULL,
    jahrgangsstufen TEXT NOT NULL,
    depth INTEGER NOT NULL,
    position INTEGER,
    UNIQUE (lehrplan_iri, iri)
);
CREATE INDEX node_lehrplan ON node(lehrplan_iri);
CREATE VIRTUAL TABLE node_fts USING fts5(
    label, parent_label, content='node', content_rowid='id', tokenize='trigram'
);
"""


@dataclass(frozen=True)
class LehrplanRecord:
    """Head fields of one curriculum as harvested."""

    iri: str
    label: str
    bundesland_code: str
    bundesland: str
    schularten: list[str] = field(default_factory=list)
    schulfaecher: list[str] = field(default_factory=list)
    jahrgangsstufen: list[str] = field(default_factory=list)
    schulstufen: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NodeHit:
    """A curriculum element whose label or parent label contains a search keyword."""

    iri: str
    label: str
    rollen: list[str]
    parent_iri: str | None
    parent_label: str
    jahrgangsstufen: list[str]
    depth: int
    lehrplan: LehrplanRecord
    matched_in: str  # "label" or "parent"


def _dump(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def _load(text: str) -> list[str]:
    loaded: list[str] = json.loads(text)
    return loaded


def _record(row: sqlite3.Row) -> LehrplanRecord:
    return LehrplanRecord(
        iri=row["lp_iri"],
        label=row["lp_label"],
        bundesland_code=row["bundesland_code"],
        bundesland=row["bundesland"],
        schularten=_load(row["schularten"]),
        schulfaecher=_load(row["schulfaecher"]),
        jahrgangsstufen=_load(row["lp_jahrgangsstufen"]),
        schulstufen=_load(row["schulstufen"]),
    )


class LehrplanCacheError(RuntimeError):
    """The cache file exists and claims the right schema, but SQLite cannot read what is needed."""


class LehrplanStore:
    """Read side of the cache; every method copes with a missing file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def state(self) -> str:
        """``missing`` without a file, ``unreadable`` when SQLite cannot read it or another schema version
        wrote it, ``ok`` otherwise; operators repair an unreadable file instead of looking for a missing one."""
        if not self.exists:
            return "missing"
        try:
            version = self._read_meta().get("schema_version")
        except sqlite3.Error as exc:
            log.warning("lehrplan cache %s is unreadable: %s", self.path, exc)
            return "unreadable"
        return "ok" if version == SCHEMA_VERSION else "unreadable"

    @property
    def available(self) -> bool:
        """A readable cache written by this schema version."""
        return self.state == "ok"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def meta(self) -> dict[str, str]:
        if not self.exists:
            return {}
        try:
            return self._read_meta()
        except sqlite3.Error as exc:
            log.warning("lehrplan cache %s is unreadable: %s", self.path, exc)
            return {}

    def _read_meta(self) -> dict[str, str]:
        with closing(self._connect()) as connection:
            return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM meta")}

    def counts(self) -> dict[str, Any]:
        empty: dict[str, Any] = {"lehrplaene": {}, "nodes": 0}
        if not self.available:
            return empty
        try:
            return self._counts()
        except sqlite3.Error as exc:
            log.warning("lehrplan cache %s cannot be counted: %s", self.path, exc)
            return empty

    def _counts(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            per_state = {
                row["bundesland_code"]: row["n"]
                for row in connection.execute(
                    "SELECT bundesland_code, COUNT(*) AS n FROM lehrplan GROUP BY bundesland_code ORDER BY n DESC"
                )
            }
            nodes = connection.execute("SELECT COUNT(*) FROM node").fetchone()[0]
        return {"lehrplaene": per_state, "nodes": nodes}

    def search(
        self, keywords: Sequence[str], *, subject_terms: Sequence[str] = (), limit: int = DEFAULT_SEARCH_LIMIT
    ) -> list[NodeHit]:
        """Content nodes whose label or parent label contains one of ``keywords`` (case-insensitive).

        ``subject_terms`` are lowercase substrings of the curriculum's subject labels and title
        ("physik", "natur und technik"); with none given all subjects are searched. A cache SQLite cannot
        read raises ``LehrplanCacheError``, so callers can say so instead of reporting zero matches.
        """
        words = [word.strip() for word in keywords if len(word.strip()) >= MIN_KEYWORD_CHARS]
        state = self.state
        if not words or state == "missing":
            return []
        if state != "ok":  # checked again here: the file may have changed since the caller looked
            raise LehrplanCacheError(f"lehrplan cache {self.path.name} is unreadable or of another schema version")
        match = " OR ".join('"' + word.replace('"', '""') + '"' for word in words)
        sql = (
            "SELECT node.iri, node.label, node.rollen, node.parent_iri, node.parent_label, node.jahrgangsstufen,"
            " node.depth, lehrplan.iri AS lp_iri, lehrplan.label AS lp_label, lehrplan.bundesland_code,"
            " lehrplan.bundesland, lehrplan.schularten, lehrplan.schulfaecher,"
            " lehrplan.jahrgangsstufen AS lp_jahrgangsstufen, lehrplan.schulstufen"
            " FROM node_fts JOIN node ON node.id = node_fts.rowid JOIN lehrplan ON lehrplan.iri = node.lehrplan_iri"
            " WHERE node_fts MATCH ? AND node.matchable = 1"
        )
        params: list[Any] = [match]
        terms = [term.strip().casefold() for term in subject_terms if term.strip()]
        if terms:
            sql += " AND (" + " OR ".join("instr(lehrplan.schulfaecher_lc, ?) > 0" for _ in terms) + ")"
            params.extend(terms)
        sql += " ORDER BY node.id LIMIT ?"
        params.append(int(limit))
        folded = [word.casefold() for word in words]
        try:
            return self._hits(sql, params, folded)
        except sqlite3.Error as exc:
            raise LehrplanCacheError(f"lehrplan cache {self.path.name} is unreadable: {exc}") from exc

    def _hits(self, sql: str, params: Sequence[Any], folded: Sequence[str]) -> list[NodeHit]:
        hits: list[NodeHit] = []
        with closing(self._connect()) as connection:
            for row in connection.execute(sql, params):
                label_hit = any(word in row["label"].casefold() for word in folded)
                hits.append(
                    NodeHit(
                        iri=row["iri"],
                        label=row["label"],
                        rollen=row["rollen"].split(","),
                        parent_iri=row["parent_iri"],
                        parent_label=row["parent_label"],
                        jahrgangsstufen=_load(row["jahrgangsstufen"]),
                        depth=row["depth"],
                        lehrplan=_record(row),
                        matched_in="label" if label_hit else "parent",
                    )
                )
        return hits


class LehrplanWriter:
    """Write side: builds ``<path>.tmp`` and swaps it in on ``commit``; ``abort`` leaves the old file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._tmp = self._path.with_name(self._path.name + TMP_SUFFIX)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tmp.unlink(missing_ok=True)
        self._connection: sqlite3.Connection | None = sqlite3.connect(self._tmp)
        self._connection.executescript("PRAGMA journal_mode=MEMORY; PRAGMA synchronous=OFF;" + SCHEMA)

    def _live(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("writer is closed")
        return self._connection

    def add_lehrplan(self, record: LehrplanRecord) -> None:
        self._live().execute(
            "INSERT OR REPLACE INTO lehrplan VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.iri,
                record.label,
                record.bundesland_code,
                record.bundesland,
                _dump(record.schularten),
                _dump(record.schulfaecher),
                # Subject filter text: labels plus the title, because 377 of Saxony's 532 curricula
                # reference subject individuals without any label (measured 2026-09-17)
                " | ".join([*record.schulfaecher, record.label]).casefold(),
                _dump(record.jahrgangsstufen),
                _dump(record.schulstufen),
            ),
        )

    def add_nodes(self, lehrplan_iri: str, nodes: Sequence[HarvestedNode]) -> None:
        self._live().executemany(
            "INSERT OR IGNORE INTO node (iri, lehrplan_iri, label, parent_iri, parent_label, rollen, matchable,"
            " jahrgangsstufen, depth, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    node.iri,
                    lehrplan_iri,
                    node.label,
                    node.parent_iri,
                    node.parent_label,
                    ",".join(node.rollen),
                    int(any(role in MATCHABLE_ROLES for role in node.rollen)),
                    _dump(node.jahrgangsstufen),
                    node.depth,
                    node.position,
                )
                for node in nodes
            ],
        )

    def set_meta(self, values: Mapping[str, str]) -> None:
        self._live().executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", list(values.items()))

    def commit(self) -> Path:
        connection = self._live()
        connection.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        connection.execute("INSERT INTO node_fts(node_fts) VALUES ('rebuild')")
        connection.commit()
        connection.close()
        self._connection = None
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(self._tmp, self._path)
                break
            except PermissionError:  # Windows: a reader still holds the old file for a moment
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(0.2 * (attempt + 1))
        return self._path

    def abort(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._tmp.unlink(missing_ok=True)
