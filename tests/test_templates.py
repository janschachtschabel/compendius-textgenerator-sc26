from pathlib import Path
from typing import Any

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


def test_a_broken_custom_template_does_not_take_the_others_down(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    manager.save(Template(id="gut", name="Gut", slots=[TemplateSlot(id="a", slot="praxis", title="Praxis")]))
    (tmp_path / "kaputt.json").write_text("{ kein JSON", encoding="utf-8")
    with caplog.at_level("ERROR"):
        assert {"sc26", "gut"} <= {template.id for template in manager.list()}
        assert manager.get("gut").name == "Gut" and manager.get("sc26").builtin
    assert "kaputt.json" in caplog.text


@pytest.mark.parametrize("content", ["[]", "null", "42", '"sc26"'])
def test_a_custom_file_without_a_json_object_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, content: str
) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    (tmp_path / "kein_objekt.json").write_text(content, encoding="utf-8")
    with caplog.at_level("ERROR"):
        assert "sc26" in {template.id for template in manager.list()}
        assert manager.get("sc26").builtin
    assert "kein_objekt.json" in caplog.text


def test_a_custom_file_that_vanishes_while_listing_is_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    manager.save(Template(id="gut", name="Gut", slots=[TemplateSlot(id="a", slot="praxis", title="Praxis")]))
    (tmp_path / "weg.json").write_text("{}", encoding="utf-8")
    original = Path.stat

    def deleted_after_glob(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == "weg.json":  # deleted by an operator between the directory listing and the stat call
            raise FileNotFoundError(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", deleted_after_glob)
    assert manager.get("gut").name == "Gut" and manager.get("sc26").builtin


def test_custom_templates_are_read_again_only_after_a_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = TemplateManager(custom_dir=tmp_path)
    manager.save(Template(id="mein", name="Mein", slots=[TemplateSlot(id="a", slot="praxis", title="Praxis")]))
    reads: list[str] = []
    original = Path.read_text

    def counting(self: Path, *args: Any, **kwargs: Any) -> str:
        reads.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    for _ in range(3):
        manager.get("mein")
        manager.list()
    assert reads.count("mein.json") <= 1  # every compendium request asks for its template
    manager.save(manager.get("mein"))
    assert manager.get("mein").version == 2
