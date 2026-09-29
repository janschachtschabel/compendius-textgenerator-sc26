"""Reopen archives when ``active.json`` changes (PLAN.md 4.1, step 5): one ``stat`` call per request."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.sources.zim.active import ActiveWatcher, read_active
from app.sources.zim.registry import ZimRegistry, newest_dumps

log = logging.getLogger(__name__)


class RegistryRefresher:
    """Keeps one ``ZimRegistry`` in step with the state file the sync job writes."""

    def __init__(self, registry: ZimRegistry, zim_dir: Path) -> None:
        self.registry = registry
        self.zim_dir = Path(zim_dir)
        self._watcher = ActiveWatcher(self.zim_dir)
        self._lock = threading.Lock()

    def refresh(self) -> bool:
        """Reload the registry if ``active.json`` changed since the last check; return whether it did.

        It runs before every request, /health and /metrics included, and raises nothing: an I/O error looking at the
        file answered each of them with a 500, and a failed read counted the change as seen, so the old archives
        stayed until the file changed again (audit 2026-09-29, S3). A broken file stays broken until the sync writes
        another; a failed read is tried again with the next request.
        """
        try:
            if not self._watcher.changed():
                return False
        except OSError as exc:
            log.error("cannot look at %s, keeping the current archives: %s", self._watcher.path, exc)
            return False
        with self._lock:
            try:
                state = read_active(self.zim_dir)
                paths = state.paths(self.zim_dir) if state is not None else newest_dumps(self.zim_dir)
            except ValueError as exc:
                log.error("active.json unreadable, keeping the current archives: %s", exc)
                return False
            except OSError as exc:
                self._watcher.forget()
                log.error("cannot read %s, keeping the current archives: %s", self._watcher.path, exc)
                return False
            self.registry.reload(paths)
            names = ", ".join(a.file_name for a in self.registry.archives) or "none"
            log.info("archives reloaded from %s: %s", self.zim_dir, names)
            return True
