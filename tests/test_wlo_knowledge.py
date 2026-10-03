"""Knowledge collection (PLAN.md 6.3, D70): every material, its text on request with budget and tolerance, sources
for part 1."""

import dataclasses
from pathlib import Path

from app.domain.models import SourceRole
from app.knowledge.segmentation import segment_source
from app.matching.lexicon import HeadingLexicon
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingError
from app.sources.wlo.errors import TimeUpError
from app.sources.wlo.knowledge import PARAGRAPH_MAX_CHARS, KnowledgeOptions, material_sources, paragraphs_from_text
from app.sources.wlo.models import MaterialRef
from app.templates.manager import TemplateManager
from tests.conftest import ROOT


def _ref(node_id: str, license_key: str, title: str = "Material") -> MaterialRef:
    return MaterialRef(
        id=node_id,
        title=title,
        description="Ein Arbeitsblatt zur Lichtbrechung mit Aufgaben zur Strahlenoptik und Bildkonstruktion.",
        url=f"https://example.org/{node_id}",
        original_id=None,
        license_key=license_key,
        mimetype="text/html",
        keywords=("Optik",),
        resource_types=("Arbeitsblatt",),
        educational_contexts=("Sekundarstufe I",),
        subjects=("Physik",),
        subject_uris=(),
    )


TEXT = (
    "Lichtbrechung\n\nTrifft Licht schräg auf die Grenzfläche zwischen Luft und Glas, ändert es seine Richtung. "
    "Der Brechungswinkel hängt vom Einfallswinkel und den beiden Medien ab.\n\n"
    "We and our partners store and/or access information on a device, such as cookies.\n\n"
    "Konstruiere den Strahlengang durch eine Sammellinse und bestimme die Bildweite mit der Linsengleichung.\n"
)


class FakeTexts:
    scope = "https://repo.test:443/edu-sharing/rest|anonymous"  # whose texts they are, as EduSharingClient.scope

    def __init__(
        self,
        texts: dict[str, str],
        *,
        fail: set[str] = frozenset(),  # type: ignore[assignment]
        late: set[str] = frozenset(),  # type: ignore[assignment]
    ) -> None:
        self.texts, self.fail, self.late = texts, fail, late
        self.calls: list[str] = []

    def text_content(self, node_id: str, *, remaining: object = None) -> str:
        self.calls.append(node_id)
        if node_id in self.fail:
            raise EduSharingError("HTTP 500 von repo")
        if node_id in self.late:  # the budget ran out while the text was on its way
            raise TimeUpError()
        return self.texts.get(node_id, "")


def test_every_material_counts_whatever_its_licence(tmp_path: Path) -> None:
    """Jan, 2026-10-01 (D70): the service is built for editorial teams with content of their own, so no licence keeps a
    material out; with the full text asked for, every one is read."""
    licensed = dataclasses.replace(_ref("a", "CC_BY_SA", "Brechung"), license_version="3.0", authors=("Dieter Welz",))
    refs = [licensed, _ref("b", "CC_BY_NC_SA", "Gesperrt"), _ref("c", "CC_0", "Leer")]
    client = FakeTexts({"a": TEXT, "c": ""})
    result = material_sources(client, TtlCache(tmp_path / "c.db"), refs, options=KnowledgeOptions(), fulltext=True)
    assert sorted(client.calls) == ["a", "b", "c"] and result.empty == 0 and result.failed == []
    assert [source.title for source in result.sources] == ["Brechung", "Gesperrt", "Leer"]
    source = result.sources[0]
    assert source.project == "wlo_material" and source.role is SourceRole.MATERIAL and source.origin == "material"
    assert source.license == "CC BY-SA 3.0" and source.authors == ["Dieter Welz"]
    assert source.url == "https://example.org/a" and source.source_id == "wlo:a"
    texts = [p.text for section in source.sections for p in section.paragraphs]
    assert texts[0].startswith("Ein Arbeitsblatt")  # the description opens the lead section
    assert any(t.startswith("Trifft Licht") for t in texts) and any(t.startswith("Konstruiere") for t in texts)
    assert not any("cookies" in t for t in texts)  # consent banners are not knowledge
    # a material without a text still brings its description
    assert [p.text[:15] for section in result.sources[2].sections for p in section.paragraphs] == ["Ein Arbeitsblat"]


def test_without_the_full_text_a_material_brings_its_description_and_nothing_is_fetched(tmp_path: Path) -> None:
    """D70: the full texts of the materials come in with a switch (knowledge_fulltext); without it a material is
    what its metadata says, and one whose description is too short for a sentence brings nothing."""
    short = dataclasses.replace(_ref("b", "CC_BY", "Kurz"), description="Arbeitsblatt Optik")
    client = FakeTexts({"a": TEXT, "b": TEXT})
    result = material_sources(
        client, TtlCache(tmp_path / "c.db"), [_ref("a", "CC_BY"), short], options=KnowledgeOptions()
    )
    assert client.calls == [] and result.empty == 1 and result.considered == 2
    (source,) = result.sources
    assert [p.text[:15] for section in source.sections for p in section.paragraphs] == ["Ein Arbeitsblat"]


def test_a_text_in_one_line_ends_at_the_characters_of_a_material() -> None:
    # Audit 2026-10-02, A07: the first line was kept whatever its length, 220,001 characters against a cap of 500
    paragraphs = paragraphs_from_text("Fachwissen " * 20_000 + ".", max_chars=500)

    assert paragraphs and sum(map(len, paragraphs)) <= 500


CONTENT_ABOUT_COOKIES = [
    "Cookies sind kleine Textdateien, die Websites zur Speicherung von Informationen auf dem Rechner verwenden.",
    "Ein Tracking-Cookie speichert, welche Seiten jemand besucht hat, und kann so ein Profil der Nutzung erstellen.",
    "Für die Einwilligung in Cookies gilt seit 2021 das TTDSG; eine Website muss vorher um Zustimmung bitten.",
    "Informed consent bedeutet, dass Versuchspersonen nach einer Aufklärung freiwillig in eine Studie einwilligen.",
    # a lesson speaks with "wir" and to teachers with "Ihre": no consent dialog (review of F08)
    "Wir untersuchen in dieser Stunde, wie Cookies funktionieren und welche Daten sie speichern.",
    "Was wir über Cookies wissen sollten: Sie sind kleine Textdateien im Browser des Rechners.",
    "Wenn wir eine Website besuchen, legt sie oft Cookies auf unserem Rechner ab, ohne zu fragen.",
    "Unsere Klasse hat gesammelt, welche Websites Cookies setzen und wofür sie sie brauchen.",
    "Wir lernen, wie man Cookies im Browser löscht und das Tracking durch Werbefirmen verhindert.",
    "Ihre Schülerinnen und Schüler erkunden, wie Cookies das Surfverhalten aufzeichnen können.",
    "Man sollte nicht einfach alle Cookies akzeptieren, nur damit das Fenster verschwindet.",
]
CONSENT_NOTICES = [
    # LEIFIphysik, 2026-10-04, from the text the repository extracted
    "Wir nutzen Cookies und ähnliche Technologien, um Ihnen ein optimales Nutzererlebnis zu bieten: CMS Funktionen, "
    "Technisch notwendig, Statistiken, Barrierefreiheit & Externe Medien.",
    # the consent dialog of a publisher in 51 of 151 material texts (M68), without the word "cookie"
    "Ein Teil der von diesem Anbieter erhobenen Daten dient der Personalisierung sowie der Messung der "
    "Werbewirksamkeit. Der Anbieter kann IP-Adressen für die Erfolgsmessung und Personalisierung von Werbung nutzen.",
    "Diese Website verwendet Cookies. Mit der weiteren Nutzung erklären Sie sich damit einverstanden.",
    "Alle Cookies akzeptieren oder nur die technisch notwendigen zulassen? Ihre Auswahl können Sie jederzeit ändern.",
    "Wir und unsere Partner speichern und/oder greifen auf Informationen auf einem Gerät zu, etwa auf Cookies.",
    "We and our partners store and/or access information on a device, such as cookies and unique identifiers.",
    "This website uses cookies to ensure you get the best experience on our website. Learn more about consent.",
    "Datenschutzeinstellungen: Hier können Sie festlegen, welche Dienste Daten über Sie sammeln dürfen.",
    "Wir verwenden Cookies, um unsere Website für Sie optimal zu gestalten und fortlaufend zu verbessern.",
    "Unsere Website setzt Cookies ein, um die Nutzung zu analysieren und Inhalte anzupassen.",
    "Auf dieser Website werden Cookies verwendet, die für den Betrieb technisch notwendig sind.",
]


def test_text_about_cookies_is_knowledge_a_consent_notice_is_not() -> None:
    """Audit 2026-10-03, F08: every line naming "cookie" or "consent" went, "Cookies sind kleine Textdateien …" with
    it; and the consent dialog that stood in 51 of 151 material texts (M68) passed, since it names no cookie."""
    assert paragraphs_from_text("\n".join(CONTENT_ABOUT_COOKIES), 10_000) == CONTENT_ABOUT_COOKIES
    assert paragraphs_from_text("\n".join(CONSENT_NOTICES), 10_000) == []


def test_a_consent_notice_in_a_text_of_one_line_takes_its_piece_not_the_text() -> None:
    """A text may come as one line (A07): a notice in it cost the whole text."""
    lesson = " ".join(["Trifft Licht schräg auf eine Grenzfläche, ändert es seine Richtung."] * 40)
    paragraphs = paragraphs_from_text(f"{lesson} {CONSENT_NOTICES[0]} {lesson}", 100_000)

    assert sum(len(p) for p in paragraphs) >= 2 * len(lesson) - 2_000
    assert not any("Wir nutzen Cookies" in p for p in paragraphs)


def test_a_long_line_becomes_paragraphs_at_its_sentence_ends() -> None:
    sentence = "Trifft Licht schräg auf eine Grenzfläche, ändert es an ihr seine Richtung zum Lot hin oder davon weg. "
    line = (sentence * 60).strip()  # 6,000 characters in one line, as some extracted texts come

    paragraphs = paragraphs_from_text(line, max_chars=20_000)

    assert len(paragraphs) > 1 and all(len(p) <= PARAGRAPH_MAX_CHARS for p in paragraphs)
    assert all(p.endswith("weg.") for p in paragraphs)  # whole sentences
    assert " ".join(paragraphs) == line  # nothing lost below the cap


def test_the_last_paragraph_keeps_the_whole_sentences_that_fit() -> None:
    first = "Die Linse bündelt das Licht in einem Brennpunkt hinter dem Glas. " * 3
    second = "Ein Hohlspiegel sammelt das Licht vor seiner Fläche. " * 4
    text = f"{first.strip()}\n{second.strip()}"

    paragraphs = paragraphs_from_text(text, max_chars=len(first) + 110)

    assert paragraphs[0] == first.strip()
    assert (
        paragraphs[1]
        == "Ein Hohlspiegel sammelt das Licht vor seiner Fläche. Ein Hohlspiegel sammelt das Licht vor seiner Fläche."
    )
    assert sum(map(len, paragraphs)) <= len(first) + 110


def test_budget_failures_and_cache(tmp_path: Path) -> None:
    refs = [_ref(f"n{i}", "CC_BY") for i in range(5)]
    client = FakeTexts({f"n{i}": TEXT for i in range(5)}, fail={"n1"})
    cache = TtlCache(tmp_path / "c.db")
    result = material_sources(
        client, cache, refs, options=KnowledgeOptions(max_materials=3, max_chars=120), fulltext=True
    )
    assert result.considered == 3 and result.failed == ["n1"] and len(result.sources) == 2
    # the text within max_chars, the first paragraph too (A07); the description comes on top
    assert all(
        sum(len(p.text) for s in src.sections if s.heading for p in s.paragraphs) <= 120 for src in result.sources
    )
    again = material_sources(client, cache, refs[:1], options=KnowledgeOptions(), fulltext=True)
    assert len(again.sources) == 1 and client.calls.count("n0") == 1  # second run served from the cache


def test_materials_not_started_before_the_deadline_are_skipped(tmp_path: Path) -> None:
    refs = [_ref(node_id, "CC_BY", f"Material {node_id}") for node_id in ("a", "b", "c")]
    client = FakeTexts({"a": TEXT, "b": TEXT, "c": TEXT})
    cache = TtlCache(tmp_path / "c.db")
    material_sources(client, cache, refs[2:], options=KnowledgeOptions(), fulltext=True)  # a cached text is used
    client.calls.clear()  # even after the deadline
    left = iter([60.0, 0.0, 0.0])
    result = material_sources(
        client, cache, refs, options=KnowledgeOptions(concurrency=1), remaining=lambda: next(left), fulltext=True
    )
    assert client.calls == ["a"]
    assert result.timed_out == 1 and [source.title for source in result.sources] == ["Material a", "Material c"]


def test_a_text_the_budget_ends_on_its_way_counts_as_timed_out_not_as_failed(tmp_path: Path) -> None:
    """A request waits at most the time left; a text it could not bring is the budget's doing (A06)."""
    refs = [_ref(node_id, "CC_BY", f"Material {node_id}") for node_id in ("a", "b")]
    client = FakeTexts({"a": TEXT, "b": TEXT}, late={"b"})
    result = material_sources(
        client, TtlCache(tmp_path / "c.db"), refs, options=KnowledgeOptions(), remaining=lambda: 1.0, fulltext=True
    )
    assert result.timed_out == 1 and result.failed == [] and [s.title for s in result.sources] == ["Material a"]


def test_the_text_of_a_material_becomes_chunks_of_part_one(tmp_path: Path) -> None:
    """Segmented with the real lexicon, as the service does it: the text is knowledge, not a list of references."""
    lexicon = HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml").with_template(TemplateManager().get("sc26"))
    client = FakeTexts({"a": TEXT})
    result = material_sources(
        client, TtlCache(tmp_path / "c.db"), [_ref("a", "CC_BY")], options=KnowledgeOptions(), fulltext=True
    )
    material = result.sources[0]
    chunks = segment_source(material, lexicon)
    assert [chunk.text[:12] for chunk in chunks] == ["Ein Arbeitsb", "Trifft Licht", "Konstruiere "]
    assert material.reference_lines == []  # nothing of the text lands among the further sources
    assert [chunk.lexicon_slot for chunk in chunks] == [None, None, None]  # the heading claims no block
