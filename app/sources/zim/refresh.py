"""Reopen archives when ``active.json`` changes (PLAN.md 4.1, step 5): one ``stat`` call per request."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.sources.zim.active import ActiveWatcher, read_active
from app.sources.zim.registry import ZimRegistry

log = logging.getLogger(__name__)


class RegistryRefresher:
    """Keeps one ``ZimRegistry`` in step with the state file the sync job writes."""

    def __init__(self, registry: ZimRegistry, zim_dir: Path) -> None:
        self.registry = registry
        self.zim_dir = Path(zim_dir)
        self._watcher = ActiveWatcher(self.zim_dir)
        self._lock = threading.Lock()

    def refresh(self) -> bool:
        """Reload the registry if ``active.json`` changed since the last check; return whether it did."""
        if not self._watcher.changed():
            return False
        with self._lock:
            try:
                state = read_active(self.zim_dir)
            except ValueError as exc:
                log.error("active.json unreadable, keeping the current archives: %s", exc)
                return False
            paths = state.paths(self.zim_dir) if state is not None else sorted(self.zim_dir.glob("*.zim"))
            self.registry.reload(paths)
            names = ", ".join(a.file_name for a in self.registry.archives) or "none"
            log.info("archives reloaded from %s: %s", self.zim_dir, names)
            return True
