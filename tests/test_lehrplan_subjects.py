"""WLO subject vocabulary to MEM subject search terms (config/subjects.yaml)."""

from pathlib import Path

import pytest

from app.sources.lehrplan.subjects import SubjectCatalog, UnknownSubjectError

CONFIG = Path(__file__).resolve().parents[1] / "config" / "subjects.yaml"


def test_repository_catalog_resolves_ids_uris_labels_and_aliases() -> None:
    catalog = SubjectCatalog.load(CONFIG)
    assert catalog.resolve("460").label == "Physik"
    assert catalog.resolve("http://w3id.org/openeduhub/vocabs/discipline/460").label == "Physik"
    assert catalog.resolve("physik").label == "Physik"
    assert catalog.resolve("Mathe").label == "Mathematik"
    assert catalog.resolve("Erdkunde").label == "Geografie"
    assert catalog.resolve(None) is None
    assert catalog.resolve("Xyzzyplomb") is None


def test_mem_terms_are_lowercase_substrings_and_empty_for_unknown_subjects() -> None:
    catalog = SubjectCatalog.load(CONFIG)
    terms = catalog.mem_terms("Physik")
    assert "physik" in terms and "natur und technik" in terms
    assert all(term == term.casefold() for subject in catalog.subjects for term in subject.mem_terms)
    assert len({subject.id for subject in catalog.subjects}) == len(catalog.subjects)
    assert catalog.mem_terms("Xyzzyplomb") == []
    assert catalog.mem_terms(None) == []
    assert SubjectCatalog.empty().mem_terms("Physik") == []


DISCIPLINE = "http://w3id.org/openeduhub/vocabs/discipline/"


def test_several_subjects_bring_all_their_words_and_none_counts_more() -> None:
    """Subjects of a node or collection are a multi-valued field: every value weighs the same (Jan, 2026-09-24)."""
    catalog = SubjectCatalog.load(CONFIG)
    biologie, physik = DISCIPLINE + "080", DISCIPLINE + "460"
    joined = catalog.context_terms_of([biologie, physik])
    assert set(joined) == set(catalog.context_terms(biologie)) | set(catalog.context_terms(physik))
    assert sorted(joined) == sorted(catalog.context_terms_of([physik, biologie])), "the order changes nothing"
    mem = catalog.mem_terms_of([biologie, physik])
    assert {"biologie", "physik"} <= set(mem) and len(mem) == len(set(mem)), "each word once"
    assert catalog.context_terms_of([]) == [] and catalog.mem_terms_of([]) == []


def test_labels_name_known_subjects_keep_typed_names_and_leave_out_unknown_uris() -> None:
    catalog = SubjectCatalog.load(CONFIG)
    values = [DISCIPLINE + "080", "mathe", DISCIPLINE + "99999", "Astronomie", DISCIPLINE + "460"]
    assert catalog.labels_of(values) == ["Biologie", "Mathematik", "Astronomie", "Physik"]


def test_check_refuses_an_unknown_subject_and_names_the_known_ones() -> None:
    """A typo used to fall back on every subject without a word (review of 2026-09-25); now it is refused."""
    catalog = SubjectCatalog.load(CONFIG)
    for known in ("Physik", "physik", "460", DISCIPLINE + "460", "Mathe", None, ""):
        catalog.check(known)
    with pytest.raises(UnknownSubjectError) as refused:
        catalog.check("Pysik")
    assert refused.value.value == "Pysik" and len(refused.value.known) == len(catalog.subjects)
    assert "Pysik" in str(refused.value) and "Physik" in str(refused.value)
    SubjectCatalog.empty().check("Pysik")  # without subjects.yaml there is nothing to check against
