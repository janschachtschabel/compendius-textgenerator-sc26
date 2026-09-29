"""Template storage: built-in templates from the package, custom templates on the state volume.

Every compendium request asks for its template, so custom templates are parsed again only when a file
in the directory changed (name, identity, modification time, size). A broken custom file is logged and skipped;
it must not take the built-in templates down with it.

Several workers and the CLI share the directory (audit 2026-09-29, A07). A save writes a temporary file next to the
template and renames it over the old one, so a reader finds the old text or the new one, never an empty or half
file; the new file's identity (inode) tells the other workers about it even when the clock has not moved on. Saves
and deletes take a lock file in the directory, so two saves at once count to two versions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from app.domain.caller_values import listed
from app.jobs.lock import LockHeldError, acquire_lock
from app.templates.schema import STORED_UNKNOWN_FIELDS, TEMPLATE_ID_PATTERN, Template

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "builtin"
LOCK_FILE = ".templates.lock"
# A save holds the lock for reading one file and writing one: at most 0.15 s for the largest template the schema
# allows (2.5 MB, 30 saves, measured 2026-09-29). A lock this old belongs to a save that died; a waiting save outlasts
# it and takes it over.
LOCK_STALE_S = 10.0
LOCK_WAIT_S = LOCK_STALE_S + 5.0
LOCK_POLL_S = 0.01

_Signature = tuple[tuple[str, int, int, int], ...]


_TEMPLATE_ID = re.compile(TEMPLATE_ID_PATTERN)


class TemplateNotFoundError(KeyError):
    pass


def _load(path: Path, *, builtin: bool) -> Template:
    """The template stored at ``path``. A field the schema does not know is left out with a warning, not refused: the
    file may come from before a field was renamed, or from an editor's hand (audit 2026-09-29, S10)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    unknown: list[str] = []
    template = Template.model_validate({**data, "builtin": builtin}, context={STORED_UNKNOWN_FIELDS: unknown})
    if unknown:
        log.warning("template %s: fields the schema does not know left out: %s", path.name, listed(unknown))
    return template


def _signature(directory: Path) -> _Signature:
    """Name, identity, modification time and size of every custom template file: changes when any file changes. A save
    renames a new file into place, so its identity changes even where two saves share a tick of the clock and a size."""
    if not directory.exists():
        return ()
    entries = []
    for path in sorted(directory.glob("*.json")):
        try:
            stat = path.stat()
        except OSError as exc:  # deleted or replaced between the listing and this call
            log.warning("custom template %s skipped: %s", path.name, exc)
            continue
        entries.append((path.name, stat.st_ino, stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def _stored_version(path: Path) -> int | None:
    """The version in the file at ``path``, read from the file itself: another process may have saved it since this
    one filled its cache. Only the JSON, not the whole template: validation took 350 of the 500 ms a save of the
    largest template held the lock. None when there is no file, or no version in it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:  # replaced by the save, as _custom() skips it meanwhile
        log.warning("custom template %s unreadable, its version starts again: %s", path.name, exc)
        return None
    version = data.get("version", 1) if isinstance(data, dict) else None
    return version if type(version) is int else None


def _write_whole(path: Path, text: str) -> None:
    """Put ``text`` at ``path`` in one step: a temporary file in the same directory, on the disk before it is renamed
    over the target. A write that fails leaves the old file as it was."""
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp")  # not *.json: no reader lists it
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)  # gone after the rename; left over only by a write that failed


@contextmanager
def _locked(directory: Path) -> Iterator[None]:
    """Saves and deletes one after another, across the workers and CLI processes that share ``directory``."""
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            held = acquire_lock(
                directory / LOCK_FILE, stale_s=LOCK_STALE_S, now=time.time, owner=f"pid {os.getpid()} {uuid.uuid4()}\n"
            )
            break
        except LockHeldError:
            if time.monotonic() > deadline:
                raise
            time.sleep(LOCK_POLL_S)
    try:
        yield
    finally:
        held.release()


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
        for name, _identity, _mtime, _size in signature:
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
        path = self.custom_dir / f"{template.id}.json"
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        with _locked(self.custom_dir):
            current = _stored_version(path)
            version = current + 1 if current is not None else max(template.version, 1)
            stored = template.model_copy(update={"version": version, "builtin": False})
            _write_whole(path, stored.model_dump_json(indent=2, exclude={"builtin"}))
        self._custom_cache = None  # this worker reads its own save at once
        return stored

    def delete(self, template_id: str) -> bool:
        if template_id in self._builtin:
            raise ValueError(f"built-in template '{template_id}' cannot be deleted")
        if self.custom_dir is None or not _TEMPLATE_ID.fullmatch(template_id):  # no file outside custom_dir (SE-09)
            return False
        path = self.custom_dir / f"{template_id}.json"
        if not path.exists():
            return False
        with _locked(self.custom_dir):
            try:
                path.unlink()
            except FileNotFoundError:  # deleted by another process meanwhile
                return False
        self._custom_cache = None
        return True
