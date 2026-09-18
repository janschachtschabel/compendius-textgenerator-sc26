"""Template storage: built-in templates from the package, custom templates on the state volume."""

from __future__ import annotations

import json
from pathlib import Path

from app.templates.schema import Template

BUILTIN_DIR = Path(__file__).parent / "builtin"


class TemplateNotFoundError(KeyError):
    pass


class TemplateManager:
    def __init__(self, custom_dir: Path | None = None) -> None:
        self.custom_dir = custom_dir
        self._builtin = self._load_dir(BUILTIN_DIR, builtin=True)

    @staticmethod
    def _load_dir(directory: Path, *, builtin: bool) -> dict[str, Template]:
        templates: dict[str, Template] = {}
        if not directory.exists():
            return templates
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            template = Template.model_validate({**data, "builtin": builtin})
            templates[template.id] = template
        return templates

    def _custom(self) -> dict[str, Template]:
        return self._load_dir(self.custom_dir, builtin=False) if self.custom_dir else {}

    def list(self) -> list[Template]:
        merged = {**self._builtin, **self._custom()}
        return list(merged.values())

    def get(self, template_id: str) -> Template:
        custom = self._custom()
        if template_id in custom:
            return custom[template_id]
        if template_id in self._builtin:
            return self._builtin[template_id]
        raise TemplateNotFoundError(template_id)

    def save(self, template: Template) -> Template:
        if self.custom_dir is None:
            raise RuntimeError("no custom template directory configured")
        if template.id in self._builtin:
            raise ValueError(f"built-in template '{template.id}' is read-only; copy it under a new id")
        existing = self._custom().get(template.id)
        version = existing.version + 1 if existing else max(template.version, 1)
        stored = template.model_copy(update={"version": version, "builtin": False})
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        (self.custom_dir / f"{stored.id}.json").write_text(
            stored.model_dump_json(indent=2, exclude={"builtin"}), encoding="utf-8"
        )
        return stored

    def delete(self, template_id: str) -> bool:
        if template_id in self._builtin:
            raise ValueError(f"built-in template '{template_id}' cannot be deleted")
        if self.custom_dir is None:
            return False
        path = self.custom_dir / f"{template_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True
