from app.knowledge.topic import normalize_topic, topic_stem


def test_grade_qualifier_becomes_context() -> None:
    result = normalize_topic("Optik in Klasse 7")
    assert result.topic == "Optik"
    assert result.context == ["Klasse 7"]


def test_subject_prefix_and_level_in_parentheses() -> None:
    result = normalize_topic("Physik: Optik (Sek I)")
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
