"""Entity kind detection: persons, organisations and single works are not subjects."""

from app.domain.models import ArticleSection, Paragraph, Source, SourceRole
from app.knowledge.entities import classify_entity, is_subject, is_work


def _source(title: str, lead: str) -> Source:
    return Source(
        source_id=f"wikipedia:{title}",
        project="wikipedia",
        role=SourceRole.LEITQUELLE,
        title=title,
        url="u",
        is_primary=False,
        origin="linked",
        sections=[ArticleSection(heading="", path=[], level=0, paragraphs=[Paragraph(text=lead)])],
    )


def test_person_organisation_and_work_are_recognised() -> None:
    person = _source(
        "Ernst Abbe", "Ernst Karl Abbe (* 23. Januar 1840 in Eisenach; † 14. Januar 1905) war ein Physiker."
    )
    org = _source("Zentralverband", "Der Zentralverband ist ein Berufsverband der Augenoptiker in Deutschland.")
    work = _source(
        "Manfred-Sinfonie", "Die Manfred-Sinfonie (opus 58) ist eine Programmsinfonie in vier Bildern nach Byron."
    )
    film = _source(
        "Die Französische Revolution", "Die Französische Revolution ist ein zweiteiliger Spielfilm aus dem Jahr 1989."
    )
    subject = _source(
        "Wellenoptik", "Als Wellenoptik bezeichnet man den Teilbereich der Optik, der Licht als Welle behandelt."
    )
    assert classify_entity(person) == "Person"
    assert classify_entity(org) == "Organisation"
    assert is_work(work)
    assert is_work(film)
    assert not is_work(subject)
    assert is_subject(subject)
    assert not any(is_subject(s) for s in (person, org, work, film))


def test_an_article_named_after_the_type_is_the_concept_not_an_instance() -> None:
    """Measured against the real Wikipedia on 2026-09-21: six concept articles came back as actors.

    The type word was matched anywhere in the first 260 characters, so an article whose own title is that
    word - or whose lead explains the word - was labelled an organisation. A wrong kind is not a missing
    one: the matching policy keeps the body text of actors out of the default block.
    """
    concept = _source("Museum", "Ein Museum ist eine dauerhafte Einrichtung, die Zeugnisse sammelt und zeigt.")
    named = _source("Deutsches Museum", "Das Deutsche Museum in München ist eines der größten Museen der Welt.")
    assert classify_entity(concept) is None
    assert classify_entity(named) == "Organisation"


def test_a_type_word_in_a_later_clause_does_not_make_an_actor() -> None:
    """The lead of the concept behind economics names companies while defining something else entirely."""
    economy = _source(
        "Wirtschaft",
        "Wirtschaft ist die Gesamtheit aller Einrichtungen und Handlungen, die der Befriedigung der "
        "Bedürfnisse dienen. Zu den wirtschaftlichen Einrichtungen gehören Unternehmen und Haushalte.",
    )
    assert classify_entity(economy) is None
