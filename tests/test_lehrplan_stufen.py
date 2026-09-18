"""Educational level ladders and the word-boundary noise rule (ported from the mem-schule-optik prototype)."""

from app.sources.lehrplan.store import LehrplanRecord
from app.sources.lehrplan.stufen import (
    OHNE_KLASSE,
    OHNE_STUFE,
    PRIMAR,
    SEK_I,
    SEK_II,
    is_noise,
    klassenstufe_sort_key,
    resolve_klassenstufe,
    resolve_schulstufe,
)


def _lehrplan(label: str, **fields: list[str]) -> LehrplanRecord:
    return LehrplanRecord(iri="https://lp/1", label=label, bundesland_code="SN", bundesland="Sachsen", **fields)


def test_word_internal_matches_are_noise_compounds_are_not() -> None:
    assert is_noise("Wahlpflichtlernbereich 9: Astrophysik", ["Licht"])
    assert is_noise("Waermestrahlung", ["Strahl"])
    assert not is_noise("Lichtbrechung an Linsen", ["Licht"])
    assert not is_noise("Strahlengang am Spiegel", ["Strahl"])
    assert not is_noise("Lernbereich 4: Wellenoptik", ["Optik"])  # keyword at the end of a compound
    assert not is_noise("Mechanische Schwingungen", ["Licht"])  # no keyword at all: nothing to judge


def test_schulstufe_ladder_prefers_data_over_derivation() -> None:
    asserted = _lehrplan("Gymnasium Physik", schulstufen=["Sekundarbereich II"])
    resolved = resolve_schulstufe(["Klassenstufe 7"], asserted)
    assert (resolved.value, resolved.source) == (SEK_II, "Daten (Lehrplan)")
    assert resolved.from_data

    derived = resolve_schulstufe(["Klassenstufe 7"], _lehrplan("Gymnasium Physik"))
    assert (derived.value, derived.source) == (SEK_I, "abgeleitet aus Jahrgangsstufe")
    assert not derived.from_data
    assert resolve_schulstufe([], _lehrplan("Sachunterricht", jahrgangsstufen=["Jahrgangsstufe 3"])).value == PRIMAR


def test_schulstufe_falls_back_to_the_curriculum_title() -> None:
    oberstufe = _lehrplan("Lehrplan Physik, Grund- und Leistungsfach in der gymnasialen Oberstufe")
    assert resolve_schulstufe([], oberstufe) == resolve_schulstufe([], oberstufe)
    assert (resolve_schulstufe([], oberstufe).value, resolve_schulstufe([], oberstufe).source) == (
        SEK_II,
        "abgeleitet aus Lehrplantitel",
    )
    assert resolve_schulstufe([], _lehrplan("Physik 7-9/10")).value == SEK_I
    assert resolve_schulstufe([], _lehrplan("Grundschule Sachunterricht")).value == PRIMAR
    unresolved = resolve_schulstufe([], _lehrplan("Physik"))
    assert (unresolved.value, unresolved.source) == (OHNE_STUFE, "nicht bestimmbar")


def test_klassenstufe_ladder_node_then_curriculum_then_title() -> None:
    lehrplan = _lehrplan("Physik 7-9/10", jahrgangsstufen=["Jahrgangsstufe 6", "Jahrgangsstufe 5"])
    assert resolve_klassenstufe(["Klassenstufe 7"], lehrplan).value == "Klassenstufe 7"
    assert resolve_klassenstufe(["Klassenstufe 7"], lehrplan).source == "Daten (Knoten)"
    from_curriculum = resolve_klassenstufe([], lehrplan)
    assert (from_curriculum.value, from_curriculum.source) == (
        "Jahrgangsstufe 5 / Jahrgangsstufe 6",
        "Daten (Lehrplan)",
    )
    from_title = resolve_klassenstufe([], _lehrplan("Physik 7-9/10"))
    assert (from_title.value, from_title.source) == ("Klassenstufen 7–10", "abgeleitet aus Lehrplantitel")
    assert resolve_klassenstufe([], _lehrplan("Physik")).value == OHNE_KLASSE


def test_klassenstufe_sort_key_orders_by_lowest_grade_with_unknown_last() -> None:
    names = [OHNE_KLASSE, "Klassenstufen 7–10", "Jahrgangsstufe 5", "Klassenstufe 12"]
    assert sorted(names, key=klassenstufe_sort_key) == [
        "Jahrgangsstufe 5",
        "Klassenstufen 7–10",
        "Klassenstufe 12",
        OHNE_KLASSE,
    ]
