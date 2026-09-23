"""Knowledge collection (PLAN.md 6.3): licence policy, text fetch with budget and tolerance, sources for part 1."""

import dataclasses
from pathlib import Path

from app.domain.models import SourceRole
from app.knowledge.segmentation import segment_source
from app.matching.lexicon import HeadingLexicon
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingError
from app.sources.wlo.knowledge import KnowledgeOptions, material_sources
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
    def __init__(self, texts: dict[str, str], *, fail: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.texts, self.fail, self.calls = texts, fail, []

    def text_content(self, node_id: str) -> str:
        self.calls.append(node_id)
        if node_id in self.fail:
            raise EduSharingError("HTTP 500 von repo")
        return self.texts.get(node_id, "")


def test_only_reusable_licences_become_sources_with_cleaned_paragraphs(tmp_path: Path) -> None:
    licensed = dataclasses.replace(_ref("a", "CC_BY_SA", "Brechung"), license_version="3.0", authors=("Dieter Welz",))
    refs = [licensed, _ref("b", "CC_BY_NC_SA", "Gesperrt"), _ref("c", "CC_0", "Leer")]
    client = FakeTexts({"a": TEXT, "c": ""})
    result = material_sources(client, TtlCache(tmp_path / "c.db"), refs, options=KnowledgeOptions())
    assert result.skipped_license == 1 and result.empty == 1 and result.failed == []
    assert sorted(client.calls) == ["a", "c"]  # the NC material is never fetched
    assert [source.title for source in result.sources] == ["Brechung"]
    source = result.sources[0]
    assert source.project == "wlo_material" and source.role is SourceRole.MATERIAL and source.origin == "material"
    assert source.license == "CC BY-SA 3.0" and source.authors == ["Dieter Welz"]
    assert source.url == "https://example.org/a" and source.source_id == "wlo:a"
    texts = [p.text for section in source.sections for p in section.paragraphs]
    assert texts[0].startswith("Ein Arbeitsblatt")  # the description opens the lead section
    assert any(t.startswith("Trifft Licht") for t in texts) and any(t.startswith("Konstruiere") for t in texts)
    assert not any("cookies" in t for t in texts)  # consent banners are not knowledge


def test_budget_failures_and_cache(tmp_path: Path) -> None:
    refs = [_ref(f"n{i}", "CC_BY") for i in range(5)]
    client = FakeTexts({f"n{i}": TEXT for i in range(5)}, fail={"n1"})
    cache = TtlCache(tmp_path / "c.db")
    result = material_sources(client, cache, refs, options=KnowledgeOptions(max_materials=3, max_chars=120))
    assert result.considered == 3 and result.failed == ["n1"] and len(result.sources) == 2
    assert all(sum(len(p.text) for s in src.sections for p in s.paragraphs) <= 120 + 200 for src in result.sources)
    again = material_sources(client, cache, refs[:1], options=KnowledgeOptions())
    assert len(again.sources) == 1 and client.calls.count("n0") == 1  # second run served from the cache


def test_materials_not_started_before_the_deadline_are_skipped(tmp_path: Path) -> None:
    refs = [_ref(node_id, "CC_BY", f"Material {node_id}") for node_id in ("a", "b", "c")]
    client = FakeTexts({"a": TEXT, "b": TEXT, "c": TEXT})
    cache = TtlCache(tmp_path / "c.db")
    cache.set("text:c", TEXT, ttl_s=60)  # a cached text costs nothing and is used even after the deadline
    checks = iter([False, True, True])
    result = material_sources(
        client, cache, refs, options=KnowledgeOptions(concurrency=1), expired=lambda: next(checks)
    )
    assert client.calls == ["a"]
    assert result.timed_out == 1 and [source.title for source in result.sources] == ["Material a", "Material c"]


def test_the_text_of_a_material_becomes_chunks_of_part_one(tmp_path: Path) -> None:
    """Segmented with the real lexicon, as the service does it: the text is knowledge, not a list of references."""
    lexicon = HeadingLexicon.load(ROOT / "config" / "heading_lexicon.yaml").with_template(TemplateManager().get("sc26"))
    client = FakeTexts({"a": TEXT})
    result = material_sources(client, TtlCache(tmp_path / "c.db"), [_ref("a", "CC_BY")], options=KnowledgeOptions())
    material = result.sources[0]
    chunks = segment_source(material, lexicon)
    assert [chunk.text[:12] for chunk in chunks] == ["Ein Arbeitsb", "Trifft Licht", "Konstruiere "]
    assert material.reference_lines == []  # nothing of the text lands among the further sources
    assert [chunk.lexicon_slot for chunk in chunks] == [None, None, None]  # the heading claims no block
