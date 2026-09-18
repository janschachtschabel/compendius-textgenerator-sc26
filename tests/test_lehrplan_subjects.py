"""WLO subject vocabulary to MEM subject search terms (config/subjects.yaml)."""

from pathlib import Path

from app.sources.lehrplan.subjects import SubjectCatalog

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
