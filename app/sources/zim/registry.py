"""Registry of the active archives (PLAN.md 4.1). What article a topic gets and what its corpus holds is decided
in app/knowledge (resolution.py, corpus_sources.py), which read the archives held here (audit 2026-09-27,
AR-03)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.domain.models import Source
from app.sources.zim.active import read_active
from app.sources.zim.archive import ZimArchive, archive_id, dump_date

log = logging.getLogger(__name__)


def newest_dumps(directory: Path) -> list[Path]:
    """The ``*.zim`` files of ``directory``, of each archive only its newest dump: both generations of an archive
    opened, and the older one led, as it sorts first (audit 2026-09-29, Q2)."""
    paths = sorted(p for p in directory.glob("*.zim")) if directory.exists() else []
    newest: dict[str, Path] = {}
    for path in paths:
        known = newest.get(archive_id(path.name))
        if known is None or dump_date(path.name) > dump_date(known.name):
            newest[archive_id(path.name)] = path
    return sorted(newest.values())


class ZimRegistry:
    """Holds the open archives, the leading source first."""

    def __init__(self, paths: Sequence[Path]) -> None:
        self.archives: list[ZimArchive] = []
        self.reload(paths)

    def reload(self, paths: Sequence[Path]) -> None:
        """Open the given archives and swap them in as one list; unreadable files are logged and skipped."""
        archives: list[ZimArchive] = []
        for path in paths:
            try:
                archives.append(ZimArchive(Path(path)))
            except Exception as exc:  # a broken archive must not take the service down
                log.error("cannot open ZIM archive %s: %s", path, exc)
        self.archives = sorted(archives, key=lambda a: (a.priority, a.file_name))

    def only(self, archive_ids: Sequence[str]) -> ZimRegistry:
        """A view on the named archives, in the order of this registry; the archives stay open and shared."""
        wanted = set(archive_ids)
        view = ZimRegistry([])
        view.archives = [archive for archive in self.archives if archive.id in wanted]
        return view

    def view(self) -> ZimRegistry:
        """The archives open now, as a registry of their own: a request reads and names the same archives from start
        to end while a reload swaps them in the shared one, and they stay open as long as the view holds them. The
        sources came from the archives at the start of a request and the snapshot of its frontmatter from those at
        its end (audit 2026-09-29, A10)."""
        view = ZimRegistry([])
        view.archives = list(self.archives)
        return view

    @classmethod
    def discover(cls, directory: Path) -> ZimRegistry:
        """The archives of ``directory``, of each archive only its newest dump (``newest_dumps``)."""
        return cls(newest_dumps(Path(directory)))

    @classmethod
    def from_active(cls, zim_dir: Path) -> ZimRegistry:
        """Registry from ``active.json``; without that file every ``*.zim`` in the directory is used.

        A corrupt state file is logged and yields an empty registry, so ``/ready`` shows the problem
        instead of the process crash-looping until the sync job rewrites the file.
        """
        try:
            state = read_active(zim_dir)
        except ValueError as exc:
            log.error("%s", exc)
            return cls([])
        if state is None:
            return cls.discover(zim_dir)
        return cls(state.paths(zim_dir))

    @property
    def ready(self) -> bool:
        return bool(self.archives)

    def has_ids(self, required: Sequence[str]) -> list[str]:
        present = {a.id for a in self.archives}
        return [r for r in required if r not in present]

    def snapshot(self) -> list[dict[str, Any]]:
        return [a.snapshot() for a in self.archives]

    @property
    def primary_archive(self) -> ZimArchive | None:
        return self.archives[0] if self.archives else None

    def lookup(self, title: str) -> Source | None:
        """Read a single article from the first archive that has it (used for actors and glossary)."""
        for archive in self.archives:
            article = archive.read(title)
            if article is None:
                continue
            if archive.parse(article).is_disambiguation:
                return None
            found = archive.to_source(article, is_primary=False)
            found.origin = "lookup"
            return found
        return None
