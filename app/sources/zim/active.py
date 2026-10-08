"""``active.json``: the archive files the service uses (PLAN.md 4.1, steps 4 and 5).

The sync job is the only writer and replaces the file atomically; API processes watch it by
file signature and reopen archives lazily. Retired files stay listed until the job prunes them.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.files import atomic_write_text

ACTIVE_FILE = "active.json"


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
    unreadable: list[str] = Field(
        default_factory=list, description="downloaded dumps libzim could not open: deleted, and not fetched again"
    )

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


def write_active(zim_dir: Path, state: ActiveState) -> Path:
    """Persist the state; readers never see a half-written file."""
    return atomic_write_text(Path(zim_dir) / ACTIVE_FILE, state.model_dump_json(indent=2))


_UNSEEN = (-1, -1)  # the signature of a file not looked at, which no file has


class ActiveWatcher:
    """Detects changes of ``active.json`` with one ``stat`` call per check (mtime and size)."""

    def __init__(self, zim_dir: Path) -> None:
        self.path = Path(zim_dir) / ACTIVE_FILE
        try:
            self._seen: tuple[int, int] | None = self._signature()
        except OSError:  # looked at again with the first request
            self._seen = _UNSEEN

    def _signature(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def changed(self) -> bool:
        """Whether the file changed since the last look; an error looking at it (``OSError``) goes to the caller."""
        current = self._signature()
        if current == self._seen:
            return False
        self._seen = current
        return True

    def forget(self) -> None:
        """Take the file as unseen: the next look counts it as changed, after a read of it failed."""
        self._seen = _UNSEEN
