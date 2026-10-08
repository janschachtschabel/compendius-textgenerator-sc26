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
import re
import sqlite3
import time
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.sources.lehrplan.tree import HarvestedNode
from app.sources.local_index import to_disk

log = logging.getLogger(__name__)

# Bump when the tables change; a cache written by another version counts as unreadable (part 2 renders
# its hint) instead of failing every compendium request.
SCHEMA_VERSION = "1"
TMP_SUFFIX = ".tmp"
MIN_KEYWORD_CHARS = 3  # the trigram tokenizer cannot match anything shorter
# Control characters leave a search word: a NUL ended the FTS5 string, and the failed query read as an unreadable
# cache - an ERROR line and available false (audit 2026-09-28, AP-03)
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
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
    """The cache file exists but cannot be used: SQLite cannot read it, or another schema version wrote it."""


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

    def intact(self) -> bool:
        """Whether ``PRAGMA quick_check`` finds every page sound - broken pages ``available`` does not see, as it reads
        the meta rows only. It reads the whole file, so it is for the harvest loop's look, not for a request."""
        if not self.available:
            return False
        try:
            with closing(self._connect()) as connection:
                found = connection.execute("PRAGMA quick_check").fetchall()
        except sqlite3.Error as exc:
            log.error("lehrplan cache %s is not usable: %s", self.path, exc)
            return False
        if [tuple(row) for row in found] != [("ok",)]:
            log.error("lehrplan cache %s failed its check: %s", self.path, [tuple(row) for row in found[:3]])
            return False
        return True

    def nodes_per_lehrplan(self) -> dict[str, int]:
        """Elements per curriculum IRI, for the harvest that replaces this cache."""
        if not self.available:
            return {}
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute("SELECT lehrplan_iri, COUNT(*) FROM node GROUP BY lehrplan_iri").fetchall()
        except sqlite3.Error as exc:
            log.warning("lehrplan cache %s cannot be counted: %s", self.path, exc)
            return {}
        return {row[0]: row[1] for row in rows}

    def matchable_per_state(self) -> dict[str, int]:
        """Elements a search can find per state code, for the harvest that replaces this cache."""
        if not self.available:
            return {}
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT lehrplan.bundesland_code, COUNT(*) FROM node"
                    " JOIN lehrplan ON lehrplan.iri = node.lehrplan_iri"
                    " WHERE node.matchable = 1 GROUP BY lehrplan.bundesland_code"
                ).fetchall()
        except sqlite3.Error as exc:
            log.warning("lehrplan cache %s cannot be counted: %s", self.path, exc)
            return {}
        return {row[0]: row[1] for row in rows}

    def lehrplaene_with_heads(self) -> set[str]:
        """IRIs of the curricula with at least one head field, for the harvest that replaces this cache."""
        if not self.available:
            return set()
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT iri FROM lehrplan WHERE schularten != '[]' OR schulfaecher != '[]'"
                    " OR jahrgangsstufen != '[]' OR schulstufen != '[]'"
                ).fetchall()
        except sqlite3.Error as exc:
            log.warning("lehrplan cache %s cannot be read: %s", self.path, exc)
            return set()
        return {row[0] for row in rows}

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
        self,
        keywords: Sequence[str],
        *,
        subject_terms: Sequence[str] = (),
        limit: int = DEFAULT_SEARCH_LIMIT,
        role_order: Sequence[str] = (),
    ) -> list[NodeHit]:
        """Content nodes whose label or parent label contains one of ``keywords`` (case-insensitive).

        ``subject_terms`` are lowercase substrings of the curriculum's subject labels and title
        ("physik", "natur und technik"); with none given all subjects are searched. Past ``limit`` the nodes of the
        roles ``role_order`` names first stay (audit 2026-09-28, PE-05), and within a role the curricula take turns:
        in the order the rows were written, the curricula harvested last lost theirs first (audit 2026-09-18, D-03).
        The hits come by role, then as written, so a search within its limit answers as before. A cache SQLite
        cannot read raises ``LehrplanCacheError``, so callers can say so instead of reporting zero matches.
        """
        words = self._searchable(keywords)
        if not words:
            return []
        where, where_params = self._where(words, subject_terms)
        ranks = "".join(" WHEN instr(',' || node.rollen || ',', ?) > 0 THEN ?" for _ in role_order)
        rank = f"CASE{ranks} ELSE {len(role_order)} END" if role_order else "0"
        sql = (
            "WITH found AS (SELECT node.iri, node.label, node.rollen, node.parent_iri, node.parent_label,"  # noqa: S608 - own fragments, every value bound
            " node.jahrgangsstufen, node.depth, lehrplan.iri AS lp_iri, lehrplan.label AS lp_label,"
            " lehrplan.bundesland_code, lehrplan.bundesland, lehrplan.schularten, lehrplan.schulfaecher,"
            " lehrplan.jahrgangsstufen AS lp_jahrgangsstufen, lehrplan.schulstufen, node.id AS node_id,"
            f" {rank} AS role_rank"
            + where
            + "), kept AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY lp_iri, role_rank ORDER BY node_id) AS turn"
            " FROM found ORDER BY role_rank, turn, node_id LIMIT ?)"
            " SELECT * FROM kept ORDER BY role_rank, node_id"
        )
        params = [value for position, role in enumerate(role_order) for value in (f",{role},", position)]
        params += [*where_params, int(limit)]
        folded = [word.casefold() for word in words]
        try:
            return self._hits(sql, params, folded)
        except sqlite3.Error as exc:
            raise LehrplanCacheError(f"lehrplan cache {self.path.name} is unreadable: {exc}") from exc

    def count(self, keywords: Sequence[str], *, subject_terms: Sequence[str] = ()) -> int:
        """How many content nodes ``search`` finds for ``keywords`` without a limit (audit 2026-09-28, PE-05)."""
        words = self._searchable(keywords)
        if not words:
            return 0
        where, params = self._where(words, subject_terms)
        try:
            with closing(self._connect()) as connection:
                return int(connection.execute("SELECT COUNT(*)" + where, params).fetchone()[0])
        except sqlite3.Error as exc:
            raise LehrplanCacheError(f"lehrplan cache {self.path.name} is unreadable: {exc}") from exc

    def _searchable(self, keywords: Sequence[str]) -> list[str]:
        """The words of ``keywords`` a search can use; none while the cache is missing, an error while it is broken."""
        cleaned = (CONTROL_CHARS.sub("", word).strip() for word in keywords)
        words = [word for word in cleaned if len(word) >= MIN_KEYWORD_CHARS]
        state = self.state
        if not words or state == "missing":
            return []
        if state != "ok":  # checked again here: the file may have changed since the caller looked
            raise LehrplanCacheError(f"lehrplan cache {self.path.name} is unreadable or of another schema version")
        return words

    @staticmethod
    def _where(words: Sequence[str], subject_terms: Sequence[str]) -> tuple[str, list[Any]]:
        """FROM and WHERE of a search, with its parameters. Each word is a quoted phrase, its quotes doubled: without
        control characters every other one is a literal to FTS5, so the expression is always well-formed and an error
        of the search is one of the cache."""
        where = (
            " FROM node_fts JOIN node ON node.id = node_fts.rowid JOIN lehrplan ON lehrplan.iri = node.lehrplan_iri"
            " WHERE node_fts MATCH ? AND node.matchable = 1"
        )
        params: list[Any] = [" OR ".join('"' + word.replace('"', '""') + '"' for word in words)]
        terms = [term.strip().casefold() for term in subject_terms if term.strip()]
        if terms:
            where += " AND (" + " OR ".join("instr(lehrplan.schulfaecher_lc, ?) > 0" for _ in terms) + ")"
            params.extend(terms)
        return where, params

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
                    int(node.matchable),
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
        # written without journal and synchronous: the pages go to the disk before the swap makes them the cache, or a
        # crash right after it could leave a whole-looking file with broken pages (audit 2026-09-28, DB-02; DB-01)
        to_disk(self._tmp)
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
