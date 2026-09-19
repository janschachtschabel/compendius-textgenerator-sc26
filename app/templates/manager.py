"""Template storage: built-in templates from the package, custom templates on the state volume.

Every compendium request asks for its template, so custom templates are parsed again only when a file
in the directory changed (name, modification time, size). A broken custom file is logged and skipped;
it must not take the built-in templates down with it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.templates.schema import Template

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "builtin"

_Signature = tuple[tuple[str, int, int], ...]


class TemplateNotFoundError(KeyError):
    pass


def _load(path: Path, *, builtin: bool) -> Template:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return Template.model_validate({**data, "builtin": builtin})


def _signature(directory: Path) -> _Signature:
    """Name, modification time and size of every custom template file: changes when any file changes."""
    if not directory.exists():
        return ()
    entries = []
    for path in sorted(directory.glob("*.json")):
        try:
            stat = path.stat()
        except OSError as exc:  # deleted or replaced between the listing and this call
            log.warning("custom template %s skipped: %s", path.name, exc)
            continue
        entries.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


class TemplateManager:
    def __init__(self, custom_dir: Path | None = None) -> None:
        self.custom_dir = custom_dir
        self._builtin = {t.id: t for t in (_load(p, builtin=True) for p in sorted(BUILTIN_DIR.glob("*.json")))}
        self._custom_cache: tuple[_Signature, dict[str, Template]] | None = None

    def _custom(self) -> dict[str, Template]:
        directory = self.custom_dir
        if directory is None:
            return {}
        signature = _signature(directory)
        cached = self._custom_cache  # read once: a save in another thread may clear it meanwhile
        if cached is not None and cached[0] == signature:
            return cached[1]
        templates: dict[str, Template] = {}
        for name, _mtime, _size in signature:
            try:
                template = _load(directory / name, builtin=False)
            except (OSError, ValueError, ValidationError) as exc:
                log.error("custom template %s skipped: %s", name, exc)
                continue
            if template.id in self._builtin:  # built-in templates are read-only, as in save() and delete()
                log.error("custom template %s skipped: the id %r belongs to a built-in template", name, template.id)
                continue
            templates[template.id] = template
        self._custom_cache = (signature, templates)
        return templates

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
        self._custom_cache = None  # two saves within one clock tick can leave the signature unchanged
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
        self._custom_cache = None
        return True
