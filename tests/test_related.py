"""Link ranking blacklist: list articles and meta pages never enter a corpus."""

from app.knowledge.related import is_blacklisted


def test_blacklist_covers_lists_meta_pages_and_umbrella_terms() -> None:
    assert is_blacklisted("Liste von Programmiersprachen")
    assert is_blacklisted("Kategorie:Optik")
    assert is_blacklisted("Physik")
    assert not is_blacklisted("Wellenoptik")
    assert not is_blacklisted("Geometrische Optik")
