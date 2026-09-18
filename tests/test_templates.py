from pathlib import Path

import pytest

from app.templates.manager import TemplateManager, TemplateNotFoundError
from app.templates.schema import Template, TemplateSlot


def test_builtin_templates_load() -> None:
    manager = TemplateManager()
    ids = {t.id for t in manager.list()}
    assert {"sc26", "standard"} <= ids
    sc26 = manager.get("sc26")
    assert len(sc26.slots) == 13
    assert sc26.builtin


def test_sc26_follows_specification() -> None:
    sc26 = TemplateManager().get("sc26")
    generated = {s.slot for s in sc26.slots if s.is_generated}
    assert generated == {"akteure", "quellen", "glossar"}
    by_key = {s.slot: s for s in sc26.slots}
    assert by_key["entwicklung_ausblick"].facets.required == ["Zeitbezug"]
    assert by_key["akteure"].facets.required == ["Akteursfunktion"]
    assert by_key["bildung"].facets.required == ["Bildungsstufe"]
    assert by_key["regularien"].facets.required == ["Geltungsebene"]
    assert set(by_key["quellen"].facets.required) == {"Zugang", "Vertrauensgrad"}
    assert by_key["glossar"].facets.allowed == []
    assert "Alltag" in by_key["gesellschaftlicher_kontext"].inclusions


def test_custom_template_roundtrip(tmp_path: Path) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    template = Template(id="mein", name="Mein Template", slots=[TemplateSlot(id="a", slot="praxis", title="Praxis")])
    saved = manager.save(template)
    assert saved.version == 1
    again = manager.save(saved)
    assert again.version == 2
    assert manager.get("mein").version == 2
    assert manager.delete("mein")
    with pytest.raises(TemplateNotFoundError):
        manager.get("mein")


def test_builtin_templates_are_protected(tmp_path: Path) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    with pytest.raises(ValueError, match="read-only"):
        manager.save(manager.get("sc26"))
    with pytest.raises(ValueError, match="cannot be deleted"):
        manager.delete("standard")


def test_duplicate_slot_ids_are_rejected() -> None:
    with pytest.raises(ValueError):
        Template(
            id="x",
            name="x",
            slots=[TemplateSlot(id="a", slot="praxis", title="A"), TemplateSlot(id="a", slot="bildung", title="B")],
        )
