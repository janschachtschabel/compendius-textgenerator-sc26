import pytest

from app.knowledge.topic import normalize_topic, topic_stem
from app.sources.lehrplan.subjects import SubjectCatalog
from tests.conftest import ROOT

# the catalogue the service loads: what counts as a subject in "Physik: Optik"
SUBJECTS = SubjectCatalog.load(ROOT / "config" / "subjects.yaml")


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
