"""Question templates and pair parsing (app/synthesis/qa.py).

The module lost its tests with the v1 endpoint in U1 and its caller with it. POST /api/v2/qa brings it back,
so its logic needs cover again: which sentence yields which question, and how a model answer is read.
"""

from __future__ import annotations

from app.synthesis.qa import QaPair, parse_pairs, rule_based_pairs

LEVELS = ["Primar", "Sek I", "Sek II"]


def questions(text: str, *, limit: int = 10, max_answer_length: int = 300) -> list[str]:
    pairs = rule_based_pairs(text, limit=limit, max_answer_length=max_answer_length)
    return [pair.question for pair in pairs]


def test_a_definition_becomes_a_what_question() -> None:
    assert questions("Die Optik ist ein Teilgebiet der Physik und handelt vom Licht.") == [
        "Was versteht man unter Optik?"
    ]


def test_an_enumeration_asks_what_it_consists_of() -> None:
    assert questions("Ein Fernrohr besteht aus einem Objektiv und einem Okular, die Licht bündeln.") == [
        "Woraus besteht ein Fernrohr?"
    ]


def test_a_purpose_asks_what_it_is_for() -> None:
    assert questions("Eine Sammellinse dient der Bündelung von Lichtstrahlen in einem Brennpunkt.") == [
        "Wozu dient eine Sammellinse?"
    ]


def test_a_year_asks_what_happened() -> None:
    assert questions("Im Jahr 1704 veröffentlichte Newton sein Werk über die Farben des Lichts.") == [
        "Was geschah im Jahr 1704?"
    ]


def test_a_sentence_no_template_fits_yields_nothing() -> None:
    assert questions("Darüber hinaus gibt es zahlreiche weitere Gesichtspunkte zu bedenken.") == []


def test_the_answer_is_the_sentence_itself_and_is_cut_to_the_bound() -> None:
    sentence = "Die Optik ist ein Teilgebiet der Physik " + "und handelt vom Licht " * 20
    pair = rule_based_pairs(sentence, limit=1, max_answer_length=60)[0]
    assert len(pair.answer) == 60 and pair.answer.endswith("…")
    assert pair.answer.startswith("Die Optik ist ein Teilgebiet der Physik")


def test_the_same_question_is_not_asked_twice_and_the_limit_holds() -> None:
    text = (
        "Die Optik ist ein Teilgebiet der Physik und handelt vom Licht. "
        "Die Optik ist ein Teilgebiet der Naturwissenschaft und alt. "
        "Ein Fernrohr besteht aus einem Objektiv und einem Okular. "
        "Eine Sammellinse dient der Bündelung von Lichtstrahlen."
    )
    assert questions(text) == [
        "Was versteht man unter Optik?",
        "Woraus besteht ein Fernrohr?",
        "Wozu dient eine Sammellinse?",
    ]
    assert len(rule_based_pairs(text, limit=2, max_answer_length=300)) == 2


def test_short_sentences_carry_too_little_to_ask_about() -> None:
    assert questions("Licht ist schnell. Die Optik ist ein Teilgebiet der Physik und handelt vom Licht.") == [
        "Was versteht man unter Optik?"
    ]


def test_parse_pairs_reads_one_pair_per_line_and_drops_the_rest() -> None:
    answer = "Was ist Licht?;Elektromagnetische Strahlung.\nkeine Trennung in dieser Zeile\n;leere Frage\nFrage;"
    assert parse_pairs(answer, max_answer_length=300) == [
        QaPair(question="Was ist Licht?", answer="Elektromagnetische Strahlung.")
    ]


def test_parse_pairs_strips_a_numbering_the_model_added() -> None:
    pairs = parse_pairs("1. Was ist Licht?;Strahlung.\nb) Was ist Optik?;Physik.", max_answer_length=300)
    assert [pair.question for pair in pairs] == ["Was ist Licht?", "Was ist Optik?"]


def test_parse_pairs_maps_a_level_by_substring_and_falls_back_to_the_first_one() -> None:
    """Measured 2026-09-20: a label the substring rule misses silently becomes the FIRST offered level.

    "Sekundarstufe II" is a wrong label then, not a missing one, which is why POST /api/v2/qa does not
    offer levels yet (docs/umbau.md, open point). This pins what the code does today, not what it should.
    """
    answer = "Frage A;Antwort;Sek I\nFrage B;Antwort;sek ii\nFrage C;Antwort;Sekundarstufe II\nFrage D;Antwort"
    pairs = parse_pairs(answer, max_answer_length=300, level_property="Bildungsstufe", level_values=LEVELS)
    assert [pair.level_value for pair in pairs] == ["Sek I", "Sek II", "Primar", "Primar"]
    assert all(pair.level_property == "Bildungsstufe" for pair in pairs)


def test_rule_based_pairs_stamp_the_level_property_they_were_given() -> None:
    pairs = rule_based_pairs(
        "Die Optik ist ein Teilgebiet der Physik und handelt vom Licht.",
        limit=1,
        max_answer_length=300,
        level_property="Bildungsstufe",
    )
    assert pairs[0].level_property == "Bildungsstufe" and pairs[0].level_value is None
