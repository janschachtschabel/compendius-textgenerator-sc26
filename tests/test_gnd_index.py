"""The local GND index (D65): the GND records of the DNB dumps an article without a Normdaten block can get.

The dumps (Turtle, CC0) name each record's preferred and variant names and, for part of them, the Wikidata item
(owl:sameAs). The index keeps only what leads to exactly one record - an item or a name that two records share
proves nothing - as measured in M42: on the 139 correct articles whose GND the Normdaten block names, the item led to
the same number in 104 of 106 cases, the name in 88 of 89.
"""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.sources.gnd.index import GndIndex, build_gnd_index

BACKSLASH = chr(92)
PREFIX = (
    "@prefix gndo: <https://d-nb.info/standards/elementset/gnd#> .\n"
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix dcterms: <http://purl.org/dc/terms/> .\n"
    "@prefix wdrs: <http://www.w3.org/2007/05/powder-s#> .\n\n"
)
SUBJECTS: list[dict[str, Any]] = [
    {"gnd": "4067271-2", "type": "SubjectHeadingSensoStricto", "names": ["Zahl"], "variants": ["Zahlen"],
     "items": ["Q11563"]},
    {"gnd": "4017790-7", "type": "SubjectHeadingSensoStricto", "names": ["Folge <Mathematik>"]},
    {"gnd": "4145940-4", "type": "NomenclatureInBiologyOrChemistry", "names": ["Bleitetraethyl"],
     "variants": ["Tetraethylblei", "TEL"]},
    {"gnd": "4009934-9", "type": "SubjectHeadingSensoStricto", "names": ["Chat"]},
    {"gnd": "4500079-7", "type": "SubjectHeadingSensoStricto", "names": ["Chat <Informatik>"], "variants": ["Chat"]},
    {"gnd": "4099999-1", "type": "SubjectHeadingSensoStricto", "names": ['Das "Ding"'], "items": ["Q999777"]},
    {"gnd": "4099998-X", "type": "SubjectHeadingSensoStricto", "names": ["Ding an sich"], "items": ["Q999777"]},
]  # fmt: skip
PLACES: list[dict[str, Any]] = [
    {"gnd": "4005728-8", "type": "TerritorialCorporateBodyOrAdministrativeUnit", "names": ["Berlin"], "items": ["Q64"],
     "predicate": "PlaceOrGeographicName"},
]  # fmt: skip


def _string(value: str) -> str:
    return '"' + value.replace(BACKSLASH, BACKSLASH * 2).replace('"', BACKSLASH + '"') + '"'


def _objects(values: list[str]) -> str:
    """A list of objects as the DNB writes it: three to a line, the rest on indented lines after a trailing comma."""
    lines = [", ".join(values[start : start + 3]) for start in range(0, len(values), 3)]
    return ",\n    ".join(lines)


def write_gnd(path: Path, records: list[dict[str, Any]], predicate: str = "SubjectHeading") -> Path:
    """A dump shaped like the DNB's: a type block, an ``/about`` block and a block with names and links per record."""
    blocks = []
    for record in records:
        uri = f"<https://d-nb.info/gnd/{record['gnd']}>"
        about = f"<https://d-nb.info/gnd/{record['gnd']}/about>"
        name = record.get("predicate", predicate)
        blocks.append(f"{uri} a gndo:{record['type']};\n  wdrs:describedby {about} .\n")
        blocks.append(f"{about} dcterms:license <http://creativecommons.org/publicdomain/zero/1.0/> .\n")
        lines = [f'{uri} gndo:gndIdentifier "{record["gnd"]}";']
        lines.append(f"  gndo:preferredNameForThe{name} " + _objects([_string(n) for n in record["names"]]) + ";")
        if record.get("variants"):
            lines.append(f"  gndo:variantNameForThe{name} " + _objects([_string(v) for v in record["variants"]]) + ";")
        if record.get("items"):
            links = [f"<http://www.wikidata.org/entity/{item}>" for item in record["items"]]
            lines.append(
                "  owl:sameAs " + _objects([*record.get("links", []), *links, "<https://viaf.org/viaf/1>"]) + ";"
            )
        lines.append(f"  wdrs:describedby {about} .")
        blocks.append("\n".join(lines) + "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(PREFIX + "\n".join(blocks))
    return path


def write_dumps(directory: Path, version: str = "20260217") -> list[tuple[Path, str]]:
    return [
        (write_gnd(directory / f"authorities-gnd-sachbegriff_lds_{version}.ttl.gz", SUBJECTS), "Sachbegriff"),
        (write_gnd(directory / f"authorities-gnd-geografikum_lds_{version}.ttl.gz", PLACES), "Geografikum"),
    ]


@pytest.fixture
def index(tmp_path: Path) -> GndIndex:
    build_gnd_index(write_dumps(tmp_path / "dumps"), tmp_path / "gnd.db")
    return GndIndex(tmp_path / "gnd.db")


def test_the_wikidata_item_of_an_article_leads_to_the_record_that_names_it(index: GndIndex) -> None:
    hit = index.find("Zahlen und Ziffern", qid="Q11563")
    assert hit is not None and (hit.number, hit.kind, hit.source) == ("4067271-2", "Sachbegriff", "wikidata")
    berlin = index.find("Berlin", qid="Q64")
    assert berlin is not None and (berlin.number, berlin.kind) == ("4005728-8", "Geografikum")


def test_without_an_item_the_title_leads_to_the_one_record_of_that_name(index: GndIndex) -> None:
    hit = index.find("Zahl", qid=None)
    assert hit is not None and (hit.number, hit.source) == ("4067271-2", "name")
    variant = index.find("Tetraethylblei", qid=None)
    assert variant is not None and variant.number == "4145940-4", "a variant name counts"
    assert index.find("tetraethylblei", qid=None) is not None, "case does not matter"


def test_a_wikipedia_qualifier_is_asked_as_the_gnd_writes_it(index: GndIndex) -> None:
    hit = index.find("Folge (Mathematik)", qid=None)
    assert hit is not None and hit.number == "4017790-7"


def test_a_name_or_an_item_that_two_records_share_proves_nothing(index: GndIndex) -> None:
    assert index.find("Chat", qid=None) is None, "Chat and Chat <Informatik> both carry the name"
    assert index.find("Irgendwas", qid="Q999777") is None, "two records name the same item"


def test_the_item_goes_before_the_name(index: GndIndex) -> None:
    hit = index.find("Folge (Mathematik)", qid="Q11563")
    assert hit is not None and hit.number == "4067271-2" and hit.source == "wikidata"


def test_quotes_in_names_survive_the_dump(index: GndIndex) -> None:
    assert index.find('Das "Ding"', qid=None) is not None


def test_meta_names_the_release_and_the_counts(index: GndIndex) -> None:
    meta = index.meta()
    assert meta["release"] == "2026-02-17"
    assert meta["records"] == 8
    assert meta["sources"] == [
        "authorities-gnd-sachbegriff_lds_20260217.ttl.gz",
        "authorities-gnd-geografikum_lds_20260217.ttl.gz",
    ]


def test_a_missing_or_foreign_file_answers_nothing(tmp_path: Path) -> None:
    assert not GndIndex(tmp_path / "gnd.db").available
    (tmp_path / "gnd.db").write_bytes(b"kein SQLite")
    index = GndIndex(tmp_path / "gnd.db")
    assert not index.available and index.find("Zahl", qid="Q11563") is None


def test_a_build_that_reads_no_record_fails_instead_of_writing_an_empty_index(tmp_path: Path) -> None:
    empty = write_gnd(tmp_path / "authorities-gnd-sachbegriff_lds_20260217.ttl.gz", [])
    with pytest.raises(ValueError, match="no GND record"):
        build_gnd_index([(empty, "Sachbegriff")], tmp_path / "gnd.db")
    assert not (tmp_path / "gnd.db").exists()


def test_the_index_is_read_only_and_holds_only_unambiguous_pairs(index: GndIndex, tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "gnd.db") as connection:
        names = dict(connection.execute("SELECT name, gnd FROM names").fetchall())
    assert "chat" not in names and names["zahlen"] == "4067271-2"


def test_names_and_links_the_dnb_wraps_onto_the_next_line_are_read(tmp_path: Path) -> None:
    """The DNB breaks long lists of objects after a comma (2026-02: 482 lines of variants in the first 6,267 records)."""
    record = {
        "gnd": "4000009-6",
        "type": "SubjectHeadingSensoStricto",
        "names": ["Abfallbeseitigung"],
        "variants": ["Abfallentsorgung", "Hausmüllentsorgung", "Müllbeseitigung", "Müllentsorgung"],
        "links": ["<http://id.loc.gov/1>", "<http://id.ndl.go.jp/2>", "<http://www.idref.fr/3>"],
        "items": ["Q999555"],
    }
    dump = write_gnd(tmp_path / "authorities-gnd-sachbegriff_lds_20260217.ttl.gz", [record])
    with gzip.open(dump, "rt", encoding="utf-8") as handle:
        assert ',\n    "Müllentsorgung";' in handle.read(), "the dump wraps the list as the DNB does"
    build_gnd_index([(dump, "Sachbegriff")], tmp_path / "gnd.db")
    index = GndIndex(tmp_path / "gnd.db")
    wrapped = index.find("Müllentsorgung", qid=None)
    assert wrapped is not None and wrapped.number == "4000009-6"
    linked = index.find("Irgendwas", qid="Q999555")
    assert linked is not None and linked.source == "wikidata"


def test_lines_of_another_subject_are_no_part_of_the_record_before(tmp_path: Path) -> None:
    dump = write_gnd(tmp_path / "authorities-gnd-sachbegriff_lds_20260217.ttl.gz", SUBJECTS[:1])
    with gzip.open(dump, "at", encoding="utf-8") as handle:
        handle.write('\n_:b1 a gndo:SubjectHeading;\n  gndo:variantNameForTheSubjectHeading "Fremdname" .\n')
    build_gnd_index([(dump, "Sachbegriff")], tmp_path / "gnd.db")
    assert GndIndex(tmp_path / "gnd.db").find("Fremdname", qid=None) is None


def test_escapes_in_names_are_read_as_turtle_defines_them(tmp_path: Path) -> None:
    umlaut = BACKSLASH + "u00e4"  # the GND writes UTF-8, a UCHAR must still read as the letter
    beyond = BACKSLASH + "U0011FFFF"  # no code point: stays as written instead of failing the build
    names = f'"K{umlaut}se", "Tab{BACKSLASH}tstopp", "X{beyond}"'
    record = (
        "<https://d-nb.info/gnd/4000010-2> a gndo:SubjectHeadingSensoStricto;\n"
        f"  gndo:preferredNameForTheSubjectHeading {names} .\n"
    )
    dump = tmp_path / "authorities-gnd-sachbegriff_lds_20260217.ttl.gz"
    with gzip.open(dump, "wt", encoding="utf-8") as handle:
        handle.write(PREFIX + record)
    build_gnd_index([(dump, "Sachbegriff")], tmp_path / "gnd.db")
    index = GndIndex(tmp_path / "gnd.db")
    assert index.find("Käse", qid=None) is not None
    assert index.find("Tab" + chr(9) + "stopp", qid=None) is not None
    assert index.find("X" + beyond, qid=None) is not None


def test_a_build_that_reads_records_but_no_name_or_item_fails(tmp_path: Path) -> None:
    """A layout the reader no longer knows - here other name predicates - must not end as an index that answers nothing."""
    dump = write_gnd(tmp_path / "authorities-gnd-sachbegriff_lds_20260217.ttl.gz", [SUBJECTS[1]])
    with gzip.open(dump, "rt", encoding="utf-8") as handle:
        text = handle.read().replace("NameForThe", "LabelForThe")
    with gzip.open(dump, "wt", encoding="utf-8") as handle:
        handle.write(text)
    with pytest.raises(ValueError, match="no name and no Wikidata item"):
        build_gnd_index([(dump, "Sachbegriff")], tmp_path / "gnd.db")
    assert not (tmp_path / "gnd.db").exists()
