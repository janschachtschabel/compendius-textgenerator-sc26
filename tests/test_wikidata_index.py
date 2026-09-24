"""The local Wikidata index (D43): article title to Wikidata number, built from two dewiki dumps, no network.

The Kiwix dump carries no Wikidata numbers (docs/umbau.md), so they come from ``page_props`` (the property
``wikibase_item`` per page id) and ``page`` (id, namespace, title, redirect flag). Only articles count: pages of
other namespaces and redirects are left out, the latter because linking follows a redirect to its article anyway.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterable
from pathlib import Path

import pytest

from app.sources.wikidata.index import WikidataIndex, build_index

BACKSLASH = chr(92)
PAGE_COLUMNS = (
    "page_id",
    "page_namespace",
    "page_title",
    "page_is_redirect",
    "page_is_new",
    "page_random",
    "page_touched",
    "page_links_updated",
    "page_latest",
    "page_len",
    "page_content_model",
    "page_lang",
)
PROPS_COLUMNS = ("pp_page", "pp_propname", "pp_value", "pp_sortkey")
# id, namespace, title as in the dump, redirect flag
PAGES = [
    (1, 0, "Ernst_Abbe", 0),
    (2, 0, "O'Brien", 0),
    (3, 14, "Physik", 0),  # a category
    (4, 0, "Abbe", 1),  # a redirect
    (5, 0, "Römisches_Reich", 0),
    (6, 0, f"Back{BACKSLASH}slash", 0),
    (7, 0, "Ohne_Wikidata", 0),
]
PROPS = [
    (1, "wikibase_item", "Q999001"),
    (1, "page_image_free", "Abbe.jpg"),
    (2, "wikibase_item", "Q999002"),
    (3, "wikibase_item", "Q999003"),
    (4, "wikibase_item", "Q999004"),
    (5, "wikibase_item", "Q999005"),
    (6, "wikibase_item", "Q999006"),
]


def sql_string(value: str) -> str:
    return "'" + value.replace(BACKSLASH, BACKSLASH * 2).replace("'", BACKSLASH + "'") + "'"


def _inserts(table: str, chunks: list[list[str]], one_line: bool) -> str:
    """The INSERT statements as the dumps of 2026 write them - the statement alone on its line, then one tuple per
    line - or, with ``one_line``, as older dumps did: every tuple of a statement on the statement's line."""
    if one_line:
        return "".join(f"INSERT INTO `{table}` VALUES {','.join(chunk)};\n" for chunk in chunks)  # noqa: S608 - text
    return "".join(f"INSERT INTO `{table}` VALUES\n" + ",\n".join(chunk) + ";\n" for chunk in chunks)


def _dump(path: Path, table: str, columns: Iterable[str], rows: list[str], completed: str, one_line: bool) -> Path:
    """A dump shaped like the real ones: header, CREATE TABLE, two INSERT statements, the closing line."""
    column_lines = ",\n".join(f"  `{name}` varbinary(255) NOT NULL" for name in columns)
    half = max(1, len(rows) // 2)
    chunks = [chunk for chunk in (rows[:half], rows[half:]) if chunk]
    # The text of a dump file, written to disk; none of it is run as SQL
    text = (
        "-- MySQL dump 10.19  Distrib 10.3.38-MariaDB, for debian-linux-gnu (x86_64)\n--\n"
        "-- Host: localhost    Database: dewiki\n"
        f"DROP TABLE IF EXISTS `{table}`;\nCREATE TABLE `{table}` (\n{column_lines},\n"
        f"  PRIMARY KEY (`{next(iter(columns))}`)\n) ENGINE=InnoDB DEFAULT CHARSET=binary;\n"
        f"/*!40000 ALTER TABLE `{table}` DISABLE KEYS */;\n"
        + _inserts(table, chunks, one_line)
        + f"/*!40000 ALTER TABLE `{table}` ENABLE KEYS */;\n-- Dump completed on {completed}\n"
    )
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)
    return path


def write_dumps(
    directory: Path,
    pages: list[tuple[int, int, str, int]] = PAGES,
    props: list[tuple[int, str, str]] = PROPS,
    completed: str = "2026-09-07 16:21:03",
    one_line: bool = False,
) -> tuple[Path, Path]:
    """``page_props`` and ``page`` dumps of the given rows; returns their paths in that order."""
    directory.mkdir(parents=True, exist_ok=True)
    page_rows = [
        f"({pid},{ns},{sql_string(title)},{redirect},0,0.5,'20260901000000','20260901000000',1,100,'wikitext',NULL)"
        for pid, ns, title, redirect in pages
    ]
    prop_rows = [f"({pid},{sql_string(name)},{sql_string(value)},NULL)" for pid, name, value in props]
    return (
        _dump(
            directory / "dewiki-latest-page_props.sql.gz", "page_props", PROPS_COLUMNS, prop_rows, completed, one_line
        ),
        _dump(directory / "dewiki-latest-page.sql.gz", "page", PAGE_COLUMNS, page_rows, completed, one_line),
    )


@pytest.fixture
def index(tmp_path: Path) -> WikidataIndex:
    page_props, page = write_dumps(tmp_path / "dumps")
    build_index(page_props, page, tmp_path / "wikidata.db")
    return WikidataIndex(tmp_path / "wikidata.db")


def test_an_article_title_leads_to_its_wikidata_number(index: WikidataIndex) -> None:
    assert index.available
    assert index.qid("Ernst Abbe") == "Q999001"
    assert index.qid("Ernst_Abbe") == "Q999001", "the dump writes underscores, the archive spaces; both are asked"
    assert index.qid("ernst Abbe") == "Q999001", "a title starts with a capital, as in Wikipedia"


def test_quotes_backslashes_and_umlauts_in_titles_survive_the_dump(index: WikidataIndex) -> None:
    assert index.qid("O'Brien") == "Q999002"
    assert index.qid("Römisches Reich") == "Q999005"
    assert index.qid(f"Back{BACKSLASH}slash") == "Q999006"


def test_only_articles_count_not_categories_or_redirects(index: WikidataIndex) -> None:
    assert index.qid("Physik") is None, "namespace 14 is a category"
    assert index.qid("Abbe") is None, "a redirect; linking follows it to its article"
    assert index.qid("Ohne Wikidata") is None, "an article without the property has no number"
    assert index.qid("Gibt es nicht") is None


def test_meta_names_the_dump_date_and_the_number_of_articles(index: WikidataIndex) -> None:
    meta = index.meta()
    assert meta["articles"] == 4
    assert meta["dump"] == "2026-09-07"
    assert meta["sources"] == ["dewiki-latest-page_props.sql.gz", "dewiki-latest-page.sql.gz"]
    assert meta["built_at"]


def test_a_missing_index_answers_nothing_instead_of_failing(tmp_path: Path) -> None:
    index = WikidataIndex(tmp_path / "gibt_es_nicht.db")
    assert not index.exists and not index.available
    assert index.qid("Ernst Abbe") is None
    assert index.meta() == {}


def test_a_foreign_file_is_not_taken_for_an_index(tmp_path: Path) -> None:
    path = tmp_path / "wikidata.db"
    path.write_bytes(b"kein SQLite")
    index = WikidataIndex(path)
    assert index.exists and not index.available
    assert index.qid("Ernst Abbe") is None


def test_a_failed_build_keeps_the_index_that_was_there(tmp_path: Path) -> None:
    page_props, page = write_dumps(tmp_path / "dumps")
    target = tmp_path / "wikidata.db"
    build_index(page_props, page, target)
    broken = tmp_path / "broken-page.sql.gz"
    broken.write_bytes(b"not gzip at all")
    with pytest.raises(OSError):  # gzip.BadGzipFile
        build_index(page_props, broken, target)
    assert WikidataIndex(target).qid("Ernst Abbe") == "Q999001"
    assert not list(tmp_path.glob("wikidata.db.*")), "no half-built file is left behind"


def test_the_older_layout_with_all_tuples_on_one_line_reads_the_same(tmp_path: Path) -> None:
    page_props, page = write_dumps(tmp_path / "dumps", one_line=True)
    meta = build_index(page_props, page, tmp_path / "wikidata.db")
    assert meta["articles"] == 4
    assert WikidataIndex(tmp_path / "wikidata.db").qid("O'Brien") == "Q999002"


def test_a_build_that_finds_no_article_fails_instead_of_writing_an_empty_index(tmp_path: Path) -> None:
    """A dump in a layout the reader does not know must not end as an index that silently answers nothing."""
    page_props, page = write_dumps(tmp_path / "dumps", pages=[(3, 14, "Physik", 0)], props=[(3, "wikibase_item", "Q1")])
    with pytest.raises(ValueError, match="no article"):
        build_index(page_props, page, tmp_path / "wikidata.db")
    assert not (tmp_path / "wikidata.db").exists()


def test_a_dump_without_its_table_is_refused(tmp_path: Path) -> None:
    _, page = write_dumps(tmp_path / "dumps")
    with pytest.raises(ValueError, match="page_props"):
        build_index(page, page, tmp_path / "wikidata.db")
