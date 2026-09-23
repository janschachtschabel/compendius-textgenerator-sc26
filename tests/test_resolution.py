"""Topic resolution with the subject of the request (measured in M8, docs/entwicklung/02-weltwissen.md)."""

from __future__ import annotations

from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.sources.lehrplan.subjects import SubjectCatalog
from app.sources.zim.topic_rules import (
    compound_candidates,
    context_score,
    disambiguation_stems,
    inflection_variants,
    looks_like_person,
    looks_like_work,
    nominative,
    pick_meaning,
    rank_by_query,
    split_genitive,
)
from tests.conftest import ROOT


def test_generic_context_words_do_not_decide_a_meaning() -> None:
    # "Fach Physik" once made "fach" a context word, and "fach" also sits in "mehrfach" and "Fachbereich"
    stems = disambiguation_stems(["Fach Physik", "Klasse 7", "Sekundarstufe I"])
    assert stems == disambiguation_stems(["Physik"]) and not any(s.startswith("fach") for s in stems)


def test_a_subject_word_counts_once_however_many_forms_the_subject_names() -> None:
    # "Mathematik" and "mathematisch" gave two stems, and one "mathematischen" in a text counted twice
    stems = disambiguation_stems(["Mathematik", "mathematisch"])
    assert stems == disambiguation_stems(["Mathematik"])
    assert context_score(stems, "Ableitung (Informatik)", "Eine Ableitung ist ein mathematischen Begriff.") == 1


def test_context_words_match_the_beginning_of_a_word() -> None:
    stems = disambiguation_stems(["Chemie"])
    assert context_score(stems, "Chemische Bindung", "Die chemische Bindung hält Atome zusammen.") > 0
    assert context_score(stems, "Binden (Kochen)", "Binden bezeichnet das Eindicken von Soßen.") == 0


def test_a_context_word_in_the_title_outweighs_one_in_the_text() -> None:
    stems = disambiguation_stems(["Physik"])
    in_title = context_score(stems, "Rolle (Physik)", "Eine Rolle ist ein Maschinenelement.")
    in_text = context_score(stems, "Rolle (Theater)", "Die Rolle eines Schauspielers; in der Physik anders.")
    assert in_title > in_text > 0


def test_the_subject_catalog_names_context_terms_for_a_subject() -> None:
    catalog = SubjectCatalog.load(ROOT / "config" / "subjects.yaml")
    terms = catalog.context_terms("Informatik")
    assert "informatik" in terms and "computer" in terms
    assert catalog.context_terms("mathe") == catalog.context_terms("Mathematik")  # aliases lead to the same terms
    assert catalog.context_terms("Unbekanntes Fach") == []


def test_inflected_forms_lead_to_the_base_title() -> None:
    assert "Lineare Funktion" in inflection_variants("Lineare Funktionen")
    assert "Klimawandel" in inflection_variants("Klimawandels")
    assert "Vulkan" in inflection_variants("Vulkane")
    assert inflection_variants("Ohm") == []  # too short to strip anything


def test_search_hits_are_ranked_by_the_words_of_the_query() -> None:
    hits = ["Meereswärmekraftwerk", "Wasserkreislauf"]
    assert rank_by_query("Kreislauf des Wassers", hits) == "Wasserkreislauf"
    hits = ["Ursachen der Industriellen Revolution", "Französische Revolution"]
    assert rank_by_query("Ursachen der Französischen Revolution", hits) == "Französische Revolution"
    assert rank_by_query("Aufbau der Atome", ["Atommodell", "Atom"]) == "Atom"
    assert rank_by_query("Lichtlehre", ["Ernst Adalbert Voretzsch"]) is None


def test_a_film_or_a_book_is_recognised_by_its_first_sentence() -> None:
    assert looks_like_work("Die Französische Revolution ist ein zweiteiliger Spielfilm aus dem Jahr 1989.")
    assert looks_like_work("Die Blechtrommel ist ein Roman von Günter Grass.")
    assert not looks_like_work("Die Französische Revolution (1789–1799) gehört zu den folgenreichsten Ereignissen.")
    # An abbreviation in the brackets after the name does not end the first sentence
    assert looks_like_work("Der Fall (franz. La Chute) ist ein Roman von Albert Camus. Er sollte eigentlich …")


def test_a_person_is_recognised_by_the_dates_after_the_name() -> None:
    # A disambiguation page lists people with the word as surname; "Geschichte: Wende" once became a historian
    assert looks_like_person("Peter Wende (* 17. März 1936 in Athen; † 26. Juli 2017) war ein deutscher Historiker.")
    assert not looks_like_person("Als Wende wird der Prozess gesellschaftspolitischen Wandels in der DDR bezeichnet.")


def test_people_listed_below_a_meaning_come_after_all_meanings() -> None:
    stems = disambiguation_stems(["Geschichte", "historisch", "Epoche"])
    meanings = [
        ("Wende (Segeln)", "Die Wende ist ein Segelmanöver."),
        ("Wende und friedliche Revolution in der DDR", "Die Wende ist ein Abschnitt der Geschichte der DDR."),
        ("Peter Wende", "Peter Wende (* 17. März 1936) war ein Historiker der Geschichte einer Epoche, historisch."),
    ]
    assert pick_meaning(meanings, stems) == (1, True)


def test_a_person_listed_first_is_the_main_meaning() -> None:
    stems = disambiguation_stems(["Religion", "Kirche"])
    meanings = [
        ("Martin Luther", "Martin Luther (* 10. November 1483) war ein Reformator der Kirche und der Religion."),
        ("Lutherrose", "Die Lutherrose ist ein Siegel."),
    ]
    assert pick_meaning(meanings, stems) == (0, True)


def test_a_genitive_topic_yields_its_compound_or_its_head() -> None:
    assert split_genitive("Kreislauf des Wassers") == ("Kreislauf", "Wassers")
    assert split_genitive("Ursachen der Französischen Revolution") == ("Ursachen", "Französischen Revolution")
    assert split_genitive("Satz des Pythagoras") == ("Satz", "Pythagoras")
    assert split_genitive("Photosynthese") is None
    assert "Wasserkreislauf" in compound_candidates("Kreislauf", "Wassers")
    assert compound_candidates("Ursachen", "Französischen Revolution") == []  # a compound needs a single word
    assert nominative("Französischen Revolution") == "Französische Revolution"
    assert nominative("Wassers") == "Wassers"  # the noun is left to the inflection variants


def test_an_aspect_of_a_topic_resolves_to_the_topic_as_a_guess(service: CompendiumService) -> None:
    resolution = service.registry.resolve_topic("Grundlagen der Optik")
    assert resolution.title == "Optik" and resolution.method == "variant" and not resolution.confident
    assert resolution.query == resolution.normalized == "Grundlagen der Optik"


def test_the_resolution_says_how_it_found_the_article(service: CompendiumService) -> None:
    exact = service.prepare(GenerateRequest(topic="Optik", parts=["world"])).resolution
    assert exact.method == "title" and exact.confident
    # Found only through the title suggestions: right here, but the editor should look at it
    suggested = service.registry.resolve_topic("Geometrische")
    assert suggested.title == "Geometrische Optik" and suggested.method == "suggestion" and not suggested.confident


def test_an_exact_title_that_says_nothing_of_the_subject_is_a_guess(service: CompendiumService) -> None:
    # "Erdkunde: Delta" took the article on the Greek letter as a sure hit
    resolution = service.registry.resolve_topic("Optik", terms=["Musik"])
    assert resolution.title == "Optik" and resolution.method == "title" and not resolution.confident
    assert service.registry.resolve_topic("Optik", terms=["Physik"]).confident
