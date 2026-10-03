import pytest

from app.knowledge.topic import normalize_topic, title_stems, topic_as_asked, topic_stem
from app.sources.lehrplan.subjects import SubjectCatalog
from tests.conftest import ROOT

# the catalogue the service loads: what counts as a subject in "Physik: Optik"
SUBJECTS = SubjectCatalog.load(ROOT / "config" / "subjects.yaml")


@pytest.mark.parametrize(
    ("raw", "asked"),
    [
        ("Digitale Bildung in der Grundschule", "Digitale Bildung in der Grundschule"),
        ("Physik: Optik in Klasse 7", "Optik in Klasse 7"),
        ("Thema: OER-Förderungen", "OER-Förderungen"),
        ("  OER-Förderungen  ", "OER-Förderungen"),
        ("Agile Methoden:  Scrum", "Agile Methoden: Scrum"),  # no subject: the prefix is part of the topic
        ("Projektmanagement: agile Projekte", "agile Projekte"),  # a subject of the Destatis vocabulary
    ],
)
def test_the_topic_as_asked_keeps_its_qualifiers_and_loses_only_a_prefix(raw: str, asked: str) -> None:
    """D69: the writer of model-knowledge-full writes about the topic in the words of the request. The archives are
    searched for "Digitale Bildung" (D12), but a text about it alone missed the request; a subject prefix goes, it
    reaches the prompts as the subject."""
    assert topic_as_asked(normalize_topic(raw, is_subject=SUBJECTS.knows)) == asked


def test_grade_qualifier_becomes_context() -> None:
    result = normalize_topic("Optik in Klasse 7")
    assert result.topic == "Optik"
    assert result.context == ["Klasse 7"]


def test_subject_prefix_and_level_in_parentheses() -> None:
    result = normalize_topic("Physik: Optik (Sek I)", is_subject=SUBJECTS.knows)
    assert result.topic == "Optik"
    assert result.subject == "Physik"
    assert "Fach Physik" in result.context
    assert "Sek I" in result.context


def test_audience_and_level_phrase() -> None:
    result = normalize_topic("Photosynthese für die Grundschule")
    assert result.topic == "Photosynthese"
    assert result.context == ["Grundschule"]


@pytest.mark.parametrize(
    "topic",
    [
        "Universität Heidelberg",
        "Humboldt-Universität zu Berlin",
        "Technische Universität München",
        "Pädagogische Hochschule Schwyz",
        "Hochschule für Musik und Theater",
        "Geschichte der Universität",
        "Gymnasium in der DDR",
        "Studium generale",
        "Kita-Alltag",
        "Stufe 1 der Energiewende",
        "Kinder, Küche, Kirche",  # a comma joins a list, it sets no addition off
    ],
)
def test_a_qualifier_word_that_is_part_of_the_topic_stays(topic: str) -> None:
    """A level or grade was stripped wherever it stood: "Universität Heidelberg" became "Heidelberg", "Geschichte der
    Universität" "Geschichte der", "Kita-Alltag" "Alltag" (audit 2026-09-29, L3). D12 means an addition to a topic."""
    result = normalize_topic(topic)
    assert (result.topic, result.context) == (topic, [])


@pytest.mark.parametrize(
    ("query", "topic", "context"),
    [
        ("Bruchrechnung Klasse 6", "Bruchrechnung", ["Klasse 6"]),
        ("Demokratie in der Sekundarstufe I", "Demokratie", ["Sekundarstufe I"]),
        ("Plattentektonik (Oberstufe)", "Plattentektonik", ["Oberstufe"]),
        ("Optik – Grundschule", "Optik", ["Grundschule"]),
        ("Klasse 7: Optik", "Optik", ["Klasse 7"]),
    ],
)
def test_a_qualifier_added_to_the_topic_becomes_context(query: str, topic: str, context: list[str]) -> None:
    """With a lead-in, in parentheses, set off by a dash or a colon, or a grade after the topic."""
    result = normalize_topic(query)
    assert (result.topic, result.context) == (topic, context)


def test_generic_prefix_is_dropped_without_subject() -> None:
    result = normalize_topic("Thema: Bruchrechnung")
    assert result.topic == "Bruchrechnung"
    assert result.subject is None


def test_plain_topics_are_untouched() -> None:
    assert normalize_topic("Französische Revolution").topic == "Französische Revolution"
    assert normalize_topic("Künstliche Intelligenz").topic == "Künstliche Intelligenz"


def test_only_qualifier_falls_back_to_query() -> None:
    result = normalize_topic("Klasse 7")
    assert result.topic == "Klasse 7"


def test_topic_stem_matches_derived_words() -> None:
    assert topic_stem("Optik") == "opti"
    assert "opti" in "optische Geräte und Optiker"
    assert topic_stem("Photosynthese") == "photosynthes"
    assert topic_stem("Brechung (Physik)") == "brechun"
    assert topic_stem("Auge") == "auge"


def test_a_title_that_opens_with_an_article_is_stemmed_from_its_noun() -> None:
    """KO-11: "Die Zauberflöte" gave the stem "die", which nearly every German paragraph holds, so the checks that a
    side article's paragraph is about the topic let everything through."""
    assert topic_stem("Die Zauberflöte") == "zauberflöt"
    assert topic_stem("Der Prozess (Roman)") == "prozes"
    assert topic_stem("Das Kapital") == "kapita"
    assert topic_stem("Die") == "die"  # nothing but the article: it stays the stem


def test_the_stems_of_a_title_follow_the_rule_of_its_topic_stem() -> None:
    """KO-11: three rules made the stem of a topic; the stems of a title for the ranking of its linked articles now cut
    each word as the topic stem does, and a leading article is no stem ("eine" sits in "Steine" and "Leine")."""
    assert title_stems("Eine kleine Nachtmusik") == ["klein", "nachtmusi"]
    assert title_stems("Optik (Physik)") == ["opti", "physi"]  # the qualifier names the field: its links count
    assert title_stems("Französische Revolution") == ["französisch", "revolutio"]
    assert title_stems("Ei") == []  # a word of under four letters sits in too many titles
    assert title_stems("Optik")[0] == topic_stem("Optik")


@pytest.mark.parametrize(
    "prefix", ["Bio", "Theater", "DaZ", "Russisch", "Italienisch", "Werken", "Gesundheit", "Technik", "NaWi"]
)
def test_every_subject_of_the_catalogue_is_a_subject_prefix(prefix: str) -> None:
    """A fixed list of 32 subjects knew 33 of the 63 labels and aliases in config/subjects.yaml not: "Bio: Zelle"
    became "Bio-Brennstoffzelle", and the subject was lost for part 2 and the disambiguation (audit 2026-09-28,
    KO-23)."""
    result = normalize_topic(f"{prefix}: Zelle", is_subject=SUBJECTS.knows)

    assert result.topic == "Zelle" and result.subject == prefix


def test_a_prefix_no_catalogue_knows_stays_in_the_topic() -> None:
    assert normalize_topic("Kapitel: Zelle", is_subject=SUBJECTS.knows).topic == "Kapitel: Zelle"
