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
