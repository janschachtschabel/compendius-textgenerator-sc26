from app.matching.lexicon import HeadingLexicon
from app.templates.manager import TemplateManager
from app.templates.schema import Template, TemplateSlot
from tests.conftest import ROOT


def test_lexicon_maps_common_headings() -> None:
    lexicon = HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml")
    assert lexicon.classify(["Geschichte"]) == "entwicklung_ausblick"
    assert lexicon.classify(["Anwendungen"]) == "praxis"
    assert lexicon.classify(["Teilbereiche der Optik"]) == "systematik"
    assert lexicon.classify(["Rechtliche Situation"]) == "regularien"
    assert lexicon.classify(["Berufsbild"]) == "beruf_wirtschaft"
    assert lexicon.classify(["Ein völlig unbekannter Abschnitt"]) is None


def test_deepest_heading_wins() -> None:
    lexicon = HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml")
    assert lexicon.classify(["Geschichte", "Anwendungen"]) == "praxis"


def test_exclusions_and_relations() -> None:
    lexicon = HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml")
    assert lexicon.is_excluded(["Einzelnachweise"])
    assert lexicon.is_excluded(["Weblinks"])
    assert lexicon.is_relation(["Siehe auch"])
    assert not lexicon.is_excluded(["Geschichte"])


def test_template_patterns_extend_lexicon() -> None:
    lexicon = HeadingLexicon.empty()
    template = Template(
        id="t",
        name="t",
        slots=[TemplateSlot(id="s1", slot="praxis", title="Praxis", heading_patterns=["^Gerätekunde$"])],
    )
    assert lexicon.classify(["Gerätekunde"]) is None
    assert lexicon.with_template(template).classify(["Gerätekunde"]) == "praxis"


def test_lexicon_covers_all_sc26_content_slots() -> None:
    lexicon = HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml")
    template = TemplateManager().get("sc26")
    for slot in template.content_slots():
        assert slot.slot in lexicon.slot_keys, slot.slot


def test_lexicon_v2_covers_harvested_headings() -> None:
    """Fassung 2 came from a 20,000-article harvest (eval/headings_top.csv); biography stays unmapped."""
    lexicon = HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml")
    assert lexicon.version >= 2
    assert lexicon.classify(["Unternehmensgeschichte"]) == "entwicklung_ausblick"
    assert lexicon.classify(["Kulturgeschichte"]) == "gesellschaftlicher_kontext"  # exact match wins over the suffix
    assert lexicon.classify(["Vegetative Merkmale"]) == "fachinhalte"
    assert lexicon.classify(["Vorkommen und Verbreitung"]) == "fachinhalte"
    assert lexicon.classify(["Taxonomie und Systematik"]) == "systematik"
    assert lexicon.classify(["Gewinnung und Darstellung"]) == "praxis"
    assert lexicon.classify(["Heutige Nutzung"]) == "praxis"
    assert lexicon.classify(["Schutzstatus"]) == "regularien"
    assert lexicon.classify(["Rezensionen"]) == "gesellschaftlicher_kontext"
    assert lexicon.classify(["Allgemein"]) == "themendefinition"
    assert lexicon.is_excluded(["Einzelnachweise und Anmerkungen"])
    assert lexicon.is_excluded(["Schriften (Auswahl)"])
    assert lexicon.is_excluded(["Diskografie"])
    for biography in ("Leben", "Karriere", "Auszeichnungen", "Lage", "Handlung", "Sonstiges"):
        assert lexicon.classify([biography]) is None, biography


def test_lexicon_v3_prefixes_from_the_gold_confusions() -> None:
    lexicon = HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml")
    assert lexicon.version >= 3
    assert lexicon.classify(["Kritik an Demokratieschwächen und -defiziten"]) == "gesellschaftlicher_kontext"
    assert lexicon.classify(["Rezeption und Deutung des Revolutionsgeschehens"]) == "gesellschaftlicher_kontext"
    assert lexicon.classify(["Gefährdungslagen", "Gesellschaftliche Spaltung"]) == "gesellschaftlicher_kontext"
    assert lexicon.classify(["Entwicklung der Erdatmosphäre"]) == "entwicklung_ausblick"
    assert lexicon.classify(["Die 1950er Jahre: Erste moderne Programmiersprachen"]) == "entwicklung_ausblick"
    assert lexicon.classify(["Mitte des 20. Jahrhunderts: Erst Ablehnung, dann Akzeptanz"]) == "entwicklung_ausblick"
    assert lexicon.classify(["Paläoklimatischer Überblick"]) == "entwicklung_ausblick"
    assert lexicon.classify(["Evolution"]) == "entwicklung_ausblick"
    assert lexicon.classify(["Definition nach Arrhenius"]) == "fachinhalte"
    assert lexicon.classify(["Ursachen für natürliche Klimaveränderungen"]) == "fachinhalte"
    assert lexicon.classify(["Anwendungen der Optik"]) == "praxis"
    assert lexicon.classify(["Typologien demokratischer Herrschaftsorganisation"]) == "systematik"
    assert lexicon.classify(["Definition"]) == "themendefinition"  # exact match keeps its block
    assert lexicon.classify(["Entwicklungsumgebung"]) is None  # prefixes stop at the word boundary
