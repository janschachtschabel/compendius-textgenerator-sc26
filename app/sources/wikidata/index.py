"""The local Wikidata index (D43): article title to Wikidata number, from two dumps of the German Wikipedia.

The Kiwix dump carries no Wikidata numbers (docs/umbau.md), so they come from the dump tables ``page_props`` (the
property ``wikibase_item`` per page id) and ``page`` (id, namespace, title), both published at
dumps.wikimedia.org/dewiki. ``compendium wikidata build`` reads them from disk - no network, no live API - and writes
one SQLite file into the state directory; the service only reads it.

Every page of namespace 0 with an item goes in, redirects included: Wikidata links some items to a redirect on purpose
(badge "sitelink to redirect"), and the ZIM keeps redirects as pages of their own - "Nenner" leads into a section of
"Bruchrechnung" and is item Q3044574, while the number of "Bruchrechnung" would name another thing. A redirect without
an item of its own has no number. The dumps and the ZIM archive have different dates, so an article renamed in between
has no number here.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.sources.local_index import LocalIndex, write_atomically

log = logging.getLogger(__name__)

SCHEMA_VERSION = "2"  # 2 adds the English title of each article (D65); an index of schema 1 is built anew
PROPERTY = "wikibase_item"
ARTICLE_NAMESPACE = "0"

# The dumps escape quotes and backslashes with a backslash; it is spelled chr(92) to keep the patterns readable.
BACKSLASH = chr(92)
_QUOTED = "'(?:[^'" + BACKSLASH * 2 + "]|" + BACKSLASH * 2 + ".)*'"
_TUPLE_RE = re.compile(BACKSLASH + "(((?:" + _QUOTED + "|[^'()])*)" + BACKSLASH + ")")  # one tuple, its body in group 1
_FIELD_RE = re.compile("'((?:[^'" + BACKSLASH * 2 + "]|" + BACKSLASH * 2 + ".)*)'|([^,]+)")
_ESCAPE_RE = re.compile(BACKSLASH * 2 + "(.)", re.DOTALL)
_ESCAPED = {"0": "\0", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a"}
_COLUMN_RE = re.compile(r"^\s+`(\w+)`")
_COMPLETED_RE = re.compile(r"^-- Dump completed on (\d{4}-\d{2}-\d{2})")


def _unescape(value: str) -> str:
    return _ESCAPE_RE.sub(lambda match: _ESCAPED.get(match.group(1), match.group(1)), value)


def _fields(body: str, count: int) -> list[str | None]:
    """The first ``count`` values of one tuple: strings unescaped, NULL as None, numbers as written."""
    values: list[str | None] = []
    for match in _FIELD_RE.finditer(body):
        quoted, bare = match.groups()
        if quoted is not None:
            values.append(_unescape(quoted))
        else:
            raw = bare.strip()
            values.append(None if raw == "NULL" else raw)
        if len(values) == count:
            break
    return values


def _rows(path: Path, table: str, wanted: tuple[str, ...], info: dict[str, str]) -> Iterator[tuple[str | None, ...]]:
    """The ``wanted`` columns of every row of ``table`` in a gzipped MySQL dump, read as a stream.

    The column order comes from the dump's own CREATE TABLE, so a reordered schema does not shift the values.
    The dumps of 2026 put ``INSERT INTO … VALUES`` alone on its line and then one tuple per line up to the ``;``;
    older ones wrote all tuples of a statement on its line. Both are read. The closing line of the dump gives its
    date, which lands in ``info["dump"]``.
    """
    # A prefix that recognises the lines of the dump; nothing here is ever executed as SQL
    create, insert = f"CREATE TABLE `{table}` (", f"INSERT INTO `{table}` VALUES"
    columns: list[str] = []
    positions: list[int] = []
    creating = inserting = False
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if creating:
                if line.startswith(")"):
                    creating = False
                    missing = [name for name in wanted if name not in columns]
                    if missing:
                        raise ValueError(f"{path.name}: table `{table}` has no column {', '.join(missing)}")
                    positions = [columns.index(name) for name in wanted]
                elif column := _COLUMN_RE.match(line):
                    columns.append(column.group(1))
            elif inserting or line.startswith(insert):
                if not positions:
                    raise ValueError(f"{path.name}: rows of `{table}` before its CREATE TABLE")
                start = 0 if inserting else len(insert)
                inserting = not line.rstrip().endswith(";")  # the statement ends with the line that closes it
                needed = max(positions) + 1
                for match in _TUPLE_RE.finditer(line, start):
                    values = _fields(match.group(1), needed)
                    yield tuple(values[index] for index in positions)
            elif line.startswith(create):
                creating = True
            elif completed := _COMPLETED_RE.match(line):
                info["dump"] = completed.group(1)
    if not positions:
        raise ValueError(f"{path.name} holds no table `{table}`; is it the {table} dump?")


def _write(target: Path, page_props: Path, page: Path, langlinks: Path | None) -> dict[str, Any]:
    info: dict[str, str] = {}
    connection = sqlite3.connect(target)
    try:
        connection.executescript(
            "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
            "CREATE TABLE props (page_id INTEGER PRIMARY KEY, qid TEXT NOT NULL);"
            "CREATE TABLE pages (page_id INTEGER PRIMARY KEY, title TEXT NOT NULL);"
            "CREATE TABLE english (page_id INTEGER PRIMARY KEY, title TEXT NOT NULL);"
        )
        connection.executemany(
            "INSERT OR IGNORE INTO props VALUES (?, ?)",
            (
                (int(page_id), qid)
                for page_id, name, qid in _rows(page_props, "page_props", ("pp_page", "pp_propname", "pp_value"), info)
                if name == PROPERTY and page_id and qid
            ),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO pages VALUES (?, ?)",
            (
                (int(page_id), title.replace("_", " "))
                for page_id, namespace, title in _rows(page, "page", ("page_id", "page_namespace", "page_title"), info)
                if namespace == ARTICLE_NAMESPACE and page_id and title
            ),
        )
        if langlinks is not None:  # the English article of each page, whose title names its DBpedia resource
            connection.executemany(
                "INSERT OR IGNORE INTO english VALUES (?, ?)",
                (
                    (int(page_id), title.replace("_", " "))
                    for page_id, lang, title in _rows(langlinks, "langlinks", ("ll_from", "ll_lang", "ll_title"), info)
                    if lang == "en" and page_id and title
                ),
            )
        connection.executescript(
            "CREATE TABLE titles (title TEXT PRIMARY KEY, qid TEXT NOT NULL, en TEXT) WITHOUT ROWID;"
            "INSERT OR IGNORE INTO titles SELECT pages.title, props.qid, english.title"
            " FROM pages JOIN props USING (page_id) LEFT JOIN english USING (page_id);"
            "DROP TABLE pages; DROP TABLE props; DROP TABLE english;"
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        articles = connection.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
        english = connection.execute("SELECT COUNT(*) FROM titles WHERE en IS NOT NULL").fetchone()[0]
        if not articles:  # a layout the reader does not know must not end as an index that answers nothing
            raise ValueError(f"no article with a Wikidata number in {page_props.name} and {page.name}")
        meta = {
            "schema": SCHEMA_VERSION,
            "articles": str(articles),
            "english": str(english),
            "dump": info.get("dump", ""),
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "sources": json.dumps([dump.name for dump in (page_props, page, langlinks) if dump is not None]),
        }
        connection.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    return _read_meta(meta)


def build_index(page_props: Path, page: Path, target: Path, *, langlinks: Path | None = None) -> dict[str, Any]:
    """Build the index from the dumps; an index already at ``target`` stays until the new one is complete.

    Without ``langlinks`` the index has the Wikidata numbers but no English titles, and DBpedia URIs stay German."""
    page_props, page, target = Path(page_props), Path(page), Path(target)
    english = Path(langlinks) if langlinks is not None else None
    for dump in (page_props, page, english):
        if dump is not None and not dump.is_file():
            raise FileNotFoundError(f"dump not found: {dump}")
    meta = write_atomically(target, lambda partial: _write(partial, page_props, page, english))
    log.info("Wikidata index %s: %d articles from the dump of %s", target, meta["articles"], meta["dump"] or "?")
    return meta


def _read_meta(rows: dict[str, str]) -> dict[str, Any]:
    return {
        "articles": int(rows.get("articles", "0")),
        "english": int(rows.get("english", "0")),
        "dump": rows.get("dump") or None,
        "built_at": rows.get("built_at"),
        "sources": json.loads(rows.get("sources", "[]")),
    }


class WikidataIndex(LocalIndex):
    """Read-only lookups in the index; a missing or foreign file answers nothing instead of failing.

    The sync (``compendium wikidata sync``, D64) writes the file while the service runs - the first one after a new
    installation, a newer one after a newer Wikipedia archive - and the index opens it by itself (``LocalIndex``).
    """

    label = "Wikidata index"
    schema = SCHEMA_VERSION

    def read_meta(self, rows: dict[str, str]) -> dict[str, Any]:
        return _read_meta(rows)

    def qid(self, title: str) -> str | None:
        """The Wikidata number of the article with this title, or ``None``.

        The title is asked as written, then with a capital first letter as Wikipedia writes titles - but only where
        that capital is a single letter: MediaWiki keeps "ß" as it is, and "SS" is another page.
        """
        row = self._first("SELECT qid FROM titles WHERE title = ?", _forms(title))
        return str(row[0]) if row else None

    def english(self, title: str) -> str | None:
        """The title of the English article of the article with this title, asked as ``qid`` asks, or ``None``."""
        row = self._first("SELECT en FROM titles WHERE title = ?", _forms(title))
        return str(row[0]) if row and row[0] else None


def _forms(title: str) -> list[tuple[str]]:
    """A title as written and with the capital first letter Wikipedia gives it, as query parameters."""
    name = title.replace("_", " ").strip()
    if not name:
        return []
    names = [name]
    capital = name[0].upper()
    if len(capital) == 1 and capital != name[0]:
        names.append(capital + name[1:])
    return [(candidate,) for candidate in names]
