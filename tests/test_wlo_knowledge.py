"""Knowledge collection (PLAN.md 6.3): licence policy, text fetch with budget and tolerance, sources for part 1."""

import dataclasses
from pathlib import Path

from app.domain.models import SourceRole
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingError
from app.sources.wlo.knowledge import KnowledgeOptions, material_sources
from app.sources.wlo.models import MaterialRef


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
