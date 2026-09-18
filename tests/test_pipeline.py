"""End-to-end part 1 on the offline sample archives."""

import re
from pathlib import Path
from typing import Any

import pytest

from app.domain.models import SectionStatus
from app.domain.requests import GenerateRequest
from app.service import CompendiumService, TopicNotFoundError
from app.sources.zim import archive as archive_module
from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import ZimRegistry


def test_registry_loads_both_archives(registry: ZimRegistry) -> None:
    assert [a.project for a in registry.archives] == ["wikipedia", "klexikon"]
    assert registry.archives[0].has_fulltext
    assert registry.has_ids(["wikipedia_de_sample", "klexikon_de_sample"]) == []
    assert registry.has_ids(["wikipedia_de_all_nopic"]) == ["wikipedia_de_all_nopic"]


def test_resolution_follows_redirects_and_normalises(registry: ZimRegistry) -> None:
    resolution = registry.resolve_topic("Lichtlehre")
    assert resolution.title == "Optik"
    resolution = registry.resolve_topic("optik")
    assert resolution.title == "Optik"


def test_disambiguation_picks_first_real_article(registry: ZimRegistry) -> None:
    resolution = registry.resolve_topic("Optik (Begriffsklärung)")
    assert resolution.disambiguation
    assert resolution.title == "Optik"


def test_unknown_topic_is_reported(service: CompendiumService) -> None:
    with pytest.raises(TopicNotFoundError):
        service.generate(GenerateRequest(topic="Xyzzyplomb"))


def test_generate_optik(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik in Klasse 7"))
    assert result.topic == "Optik"
    assert result.resolution.normalized == "Optik"
    assert result.resolution.context == ["Klasse 7"]
    projects = {s.project for s in result.sources}
    assert {"wikipedia", "klexikon"} <= projects
    assert sum(1 for s in result.sources if s.is_primary) == 1

    markdown = result.markdown
    assert markdown.startswith("---\n")
    assert "## Teil 1 · Weltwissen" in markdown
    assert "### 1 · Themendefinition" in markdown
    assert "<!-- kompendium:section id=sc26_1 status=maschinell-extraktiv" in markdown

    by_key = {s.slot_key: s for s in result.sections}
    assert by_key["themendefinition"].text.startswith("Die Optik")
    assert by_key["quellen"].status is SectionStatus.GENERATED
    assert "TULLU" in by_key["quellen"].text
    assert by_key["glossar"].status is SectionStatus.GENERATED
    assert "skos:prefLabel" in by_key["glossar"].text
    assert by_key["akteure"].status is SectionStatus.GENERATED
    assert "Ernst Abbe" in by_key["akteure"].text

    cited = {int(n) for s in result.sections for n in re.findall(r"\[(\d+)\]", s.text) if not s.slot_key == "quellen"}
    numbers = {c.number for s in result.sections for c in s.citations}
    assert cited <= numbers, "every citation marker must have a citation record"
    assert result.audit.citations == len(numbers) > 0
    assert result.audit.sections_filled >= 7
    assert not any(f.severity == "error" for f in result.audit.lint)


def test_empty_slots_are_omitted_by_default(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Sinfonie"))
    empty = [s for s in result.sections if s.status is SectionStatus.EMPTY]
    for section in empty:
        assert f"### {section.title}" not in result.markdown
    assert result.resolution.title == "Sinfonie"


def test_note_policy_renders_empty_slots(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Sinfonie", empty_slot_policy="note"))
    empty = [s for s in result.sections if s.status is SectionStatus.EMPTY]
    if empty:
        assert "keine hinreichend passenden Abschnitte" in result.markdown


def test_standard_template(service: CompendiumService) -> None:
    result = service.generate(GenerateRequest(topic="Optik", template_id="standard"))
    assert result.template_id == "standard"
    assert len(result.sections) == 6


def test_parse_cache_evicts_the_least_recently_used_article(
    sample_zims: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = ZimArchive(sample_zims["wikipedia"])  # own instance: the session registry's cache is shared state
    monkeypatch.setattr("app.sources.zim.archive.PARSE_CACHE_SIZE", 2)
    parsed: list[str] = []
    original = archive_module.parse_article

    def counting(html: str, title: str) -> Any:
        parsed.append(title)
        return original(html, title)

    monkeypatch.setattr(archive_module, "parse_article", counting)
    articles = {title: archive.read(title) for title in ("Optik", "Ernst Abbe", "Sinfonie")}
    for title in ("Optik", "Ernst Abbe", "Optik", "Sinfonie", "Optik", "Ernst Abbe"):
        article = articles[title]
        assert article is not None
        archive.parse(article)
    # Optik stays hot; Ernst Abbe was the least recently used when Sinfonie came in
    assert parsed == ["Optik", "Ernst Abbe", "Sinfonie", "Ernst Abbe"]
