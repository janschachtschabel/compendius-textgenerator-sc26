"""Inference-time matching against the cache: keywords, noise rule, ranking, subject filter."""

from pathlib import Path

import pytest

from app.sources.lehrplan.matcher import LehrplanMatcher, boundary_keyword, build_keywords
from app.sources.lehrplan.store import LehrplanRecord, LehrplanStore, LehrplanWriter
from app.sources.lehrplan.tree import HarvestedNode

SN = LehrplanRecord(
    iri="https://lp-sachsen.org/resource/522",
    label="Gymnasium Physik",
    bundesland_code="SN",
    bundesland="Sachsen",
    schularten=["Gymnasium"],
    schulfaecher=["Physik"],
    schulstufen=["Sekundarbereich I"],
)
RP = LehrplanRecord(
    iri="https://lp-rlp.org/resource/lehrplan-7",
    label="Physik, Grund- und Leistungsfach in der gymnasialen Oberstufe",
    bundesland_code="RP",
    bundesland="Rheinland-Pfalz",
    schulfaecher=["Physik"],
)
BY = LehrplanRecord(
    iri="https://lp-bavaria.org/nt5",
    label="Natur und Technik 5",
    bundesland_code="BY",
    bundesland="Bayern",
    schulfaecher=["Natur und Technik"],
    jahrgangsstufen=["Jahrgangsstufe 5"],
)


def _node(iri: str, label: str, rollen: list[str], parent: str = "", grades: list[str] | None = None) -> HarvestedNode:
    node = HarvestedNode(iri=iri, label=label, types=(), rollen=rollen, jahrgangsstufen=grades or [], position=None)
    node.parent_label = parent
    return node


@pytest.fixture
def store(tmp_path: Path) -> LehrplanStore:
    writer = LehrplanWriter(tmp_path / "lehrplan.db")
    writer.add_lehrplan(SN)
    writer.add_nodes(
        SN.iri,
        [
            _node("sn:lb", "Lernbereich 2: Optik", ["themenbereich"], "Gymnasium Physik", ["Klassenstufe 7"]),
            _node(
                "sn:k1", "Lichtbrechung an Linsen", ["kompetenz", "inhalt"], "Lernbereich 2: Optik", ["Klassenstufe 7"]
            ),
            _node("sn:k2", "Bildentstehung beschreiben", ["kompetenz"], "Lernbereich 2: Optik", ["Klassenstufe 7"]),
            _node("sn:noise", "Wahlpflichtlernbereich 9: Astrophysik", ["themenbereich"], "Gymnasium Physik"),
        ],
    )
    writer.add_lehrplan(RP)
    writer.add_nodes(RP.iri, [_node("rp:k", "Licht als Welle und Teilchen verstehen", ["kompetenz"], "Lernbereich 7")])
    writer.add_lehrplan(BY)
    writer.add_nodes(
        BY.iri, [_node("by:i", "Schatten und Finsternisse", ["inhalt"], "Optik: Sehen und gesehen werden")]
    )
    writer.set_meta({"harvested_at": "2026-09-17T10:00:00+00:00"})
    writer.commit()
    return LehrplanStore(tmp_path / "lehrplan.db")


def test_keywords_come_from_topic_aliases_and_subtopics_without_duplicates() -> None:
    keywords = build_keywords(
        "Optik",
        aliases=["Lehre vom Licht", "optik", "Ab"],
        subtopics=["Wellenoptik", "Optik (Begriffsklärung)", "Geometrische Optik"],
    )
    assert keywords == ["Optik", "Lehre vom Licht", "Wellenoptik", "Geometrische Optik"]
    assert build_keywords("Säure-Base-Konzepte", aliases=[], subtopics=[]) == ["Säure-Base-Konzepte", "Säure", "Base"]
    assert len(build_keywords("Thema", aliases=[f"Alias {i}" for i in range(30)], subtopics=[], max_keywords=6)) == 6


def test_matches_are_ranked_role_then_label_hit_then_level_from_data(store: LehrplanStore) -> None:
    result = LehrplanMatcher(store).match(["Optik", "Licht"])
    order = [match.hit.iri for match in result.matches]
    # Themenbereich first, then competencies with the keyword in their own label, then parent-only hits,
    # then the content node; the derived level (RP title) ranks below asserted grades (SN, BY)
    assert order == ["sn:lb", "sn:k1", "rp:k", "sn:k2", "by:i"]
    assert result.total_hits == 6 and result.excluded_noise == 1
    lead = result.matches[0]
    assert (lead.schulstufe.value, lead.klassenstufe.value) == ("Sekundarstufe I", "Klassenstufe 7")
    assert lead.schulstufe.from_data and lead.klassenstufe.from_data
    by = result.matches[-1]
    assert by.klassenstufe.value == "Jahrgangsstufe 5" and by.schulstufe.source == "abgeleitet aus Jahrgangsstufe"
    assert by.keyword == "Optik" and by.hit.matched_in == "parent"


def test_subject_terms_narrow_the_curricula(store: LehrplanStore) -> None:
    matcher = LehrplanMatcher(store)
    assert {
        m.hit.lehrplan.bundesland_code for m in matcher.match(["Optik"], subject_terms=["natur und technik"]).matches
    } == {"BY"}
    assert matcher.match(["Optik"], subject_terms=["chemie"]).matches == []
    assert matcher.match([]).matches == []


def test_buried_label_match_with_a_proper_parent_hit_counts_as_parent_match(tmp_path: Path) -> None:
    """Review finding: the noise rule must not drop a node whose parent label is the real hit."""
    writer = LehrplanWriter(tmp_path / "lehrplan.db")
    writer.add_lehrplan(SN)
    writer.add_nodes(
        SN.iri,
        [
            _node("sn:wp", "Wahlpflichtbereich 3", ["kompetenz"], "Lernbereich 2: Licht und Schatten"),
            _node("sn:bild", "Bildentstehung", ["kompetenz"], "Lernbereich 2: Licht und Schatten"),
            _node("sn:noise", "Wahlpflichtbereich 4", ["kompetenz"], "Lernbereich 3: Mechanik"),
        ],
    )
    writer.commit()
    result = LehrplanMatcher(LehrplanStore(tmp_path / "lehrplan.db")).match(["Licht"])
    by_iri = {match.hit.iri: match for match in result.matches}
    assert set(by_iri) == {"sn:wp", "sn:bild"}
    assert by_iri["sn:wp"].hit.matched_in == "parent" and by_iri["sn:wp"].keyword == "Licht"
    assert by_iri["sn:wp"].score == by_iri["sn:bild"].score
    assert result.excluded_noise == 1


def test_the_topic_itself_is_never_dropped_for_length() -> None:
    long_topic = "Elektromagnetische Induktion und Wechselstrom"
    assert build_keywords(long_topic, aliases=["x" * 60], subtopics=[]) == [long_topic]


def test_only_the_topic_itself_is_split_at_its_hyphens() -> None:
    """M22: the part "affin" of the synonym "affin-lineare Funktion" found Paraffin and Affinität."""
    keywords = build_keywords("Lineare Funktion", aliases=["affin-lineare Funktion"], subtopics=["Säure-Base-Paar"])
    assert keywords == ["Lineare Funktion", "affin-lineare Funktion", "Säure-Base-Paar"]
    assert build_keywords("Säure-Base-Konzepte", aliases=[], subtopics=[]) == ["Säure-Base-Konzepte", "Säure", "Base"]


def test_a_keyword_counts_at_the_start_of_a_word_or_as_the_end_of_a_compound() -> None:
    """M22: "Erdplatten" found "Herdplatten", "Lineare Funktion" the heading "NICHT-LINEARE FUNKTIONEN"."""
    assert boundary_keyword("Lichtbrechung an Linsen", ["Licht"]) == "Licht"
    assert boundary_keyword("Eizelle und Spermium", ["Zelle"]) == "Zelle", "two letters before it make a compound"
    assert boundary_keyword("Herdplatten reinigen", ["Erdplatten"]) is None, "one letter before it is no compound"
    assert boundary_keyword("NICHT-LINEARE FUNKTIONEN", ["Lineare Funktion"]) is None, "negated by nicht-"
    assert boundary_keyword("nicht lineare Funktionen", ["Lineare Funktion"]) is None
    assert boundary_keyword("Lineare Funktionen zeichnen", ["Lineare Funktion"]) == "Lineare Funktion"
    assert boundary_keyword("Wahl\xadpflicht\xadbereich", ["Licht"]) is None, "a soft hyphen does not end a word"
