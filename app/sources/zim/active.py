"""``active.json``: the archive files the service uses (PLAN.md 4.1, steps 4 and 5).

The sync job is the only writer and replaces the file atomically; API processes watch it by
file signature and reopen archives lazily. Retired files stay listed until the job prunes them.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

ACTIVE_FILE = "active.json"
_REPLACE_ATTEMPTS = 5  # Windows refuses to replace a file another process has open for a moment


class ActiveArchive(BaseModel):
    id: str
    file: str
    uuid: str = ""
    date: str = ""
    project: str = ""
    size: int = 0
    activated_at: str = ""


class RetiredArchive(BaseModel):
    file: str
    retired_at: str


class ActiveState(BaseModel):
    version: int = 1
    profile: str = ""
    updated_at: str = ""
    archives: dict[str, ActiveArchive] = Field(default_factory=dict, description="subscription id -> archive")
    retired: list[RetiredArchive] = Field(default_factory=list)

    def paths(self, zim_dir: Path) -> list[Path]:
        return [Path(zim_dir) / archive.file for archive in self.archives.values()]


def read_active(zim_dir: Path) -> ActiveState | None:
    """Return the state or ``None`` when no file exists; a corrupt file raises ``ValueError``."""
    path = Path(zim_dir) / ACTIVE_FILE
    if not path.exists():
        return None
    try:
        return ActiveState.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValueError(f"{path} is not a valid active.json: {exc}") from exc


def atomic_write_text(target: Path, text: str) -> Path:
    """Write ``text`` to a temporary file next to ``target`` and move it into place atomically."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, target)
            break
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    return target


def write_active(zim_dir: Path, state: ActiveState) -> Path:
    """Persist the state; readers never see a half-written file."""
    return atomic_write_text(Path(zim_dir) / ACTIVE_FILE, state.model_dump_json(indent=2))


class ActiveWatcher:
    """Detects changes of ``active.json`` with one ``stat`` call per check (mtime and size)."""

    def __init__(self, zim_dir: Path) -> None:
        self.path = Path(zim_dir) / ACTIVE_FILE
        self._seen = self._signature()

    def _signature(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def changed(self) -> bool:
        current = self._signature()
        if current == self._seen:
            return False
        self._seen = current
        return True
