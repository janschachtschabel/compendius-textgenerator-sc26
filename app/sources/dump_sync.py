"""A local index kept in step with a published release of dump files: the run the Wikidata sync (D64) and the GND sync
(D65) share.

A run takes the lock next to the index (one run at a time; ``compendium … build`` by hand takes it too), writes its
status, asks for the newest release, removes what an older release left behind, downloads each file (resumable, held
to the digest the source publishes), builds the index next to the old one and swaps it, deletes the dumps and writes
the outcome. On any failure the old index stays and the status says why. A stopped container (``KeyboardInterrupt``
from ``stop_on_sigterm``) leaves ``ok`` open: that is no failure of the source, and no alert should see one.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar

import httpx

from app.files import atomic_write_text
from app.locks import HeldLock, LockHeldError, acquire_lock
from app.sources.zim.downloader import PART_SUFFIX, Downloader

log = logging.getLogger(__name__)

LOCK_STALE_S = 3 * 3600  # a run downloads and builds for minutes; hours without a sign of life mean it crashed


class ReleaseNotFoundError(RuntimeError):
    """The source offers no release to build from - yet: a later check may find one."""


@dataclass(frozen=True)
class DumpFile:
    name: str
    url: str
    size: int
    digest: str  # hex digest with the hash the sync's downloader checks


@dataclass(frozen=True)
class Release:
    id: str  # as the source names it: a run directory "20260901", a GND version "20260217"
    date: date
    files: tuple[DumpFile, ...]


def read_status(state_dir: Path, name: str) -> dict[str, Any] | None:
    """A sync's status file, ``None`` without one or when it cannot be read."""
    path = Path(state_dir) / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("%s is unreadable: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DumpSync:
    """One index file and the release it is built from; a subclass says where releases come from and how to build.

    ``find_release`` names the newest release, ``build`` turns its downloaded files (in the order of
    ``Release.files``) into the index at ``index_path``, ``summary`` picks what the status keeps of the build's meta.
    """

    status_file: ClassVar[str]
    lock_file: ClassVar[str]
    dump_dir: ClassVar[str]
    label: ClassVar[str]

    def __init__(self, index_path: Path, *, client: httpx.Client, base_url: str, downloader: Downloader) -> None:
        self.index_path = Path(index_path)
        self._dir = self.index_path.parent
        self._client = client
        self.base_url = base_url
        self._downloader = downloader

    def find_release(self) -> Release:
        raise NotImplementedError

    def build(self, files: list[Path]) -> dict[str, Any]:
        raise NotImplementedError

    def summary(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {}

    def run(self, reason: str = "") -> dict[str, Any]:
        """Download the newest release, build the index and swap it in; the old index stays on any failure.

        One run at a time: the lock is held until the dumps are gone and the status is written."""
        lock = acquire_lock(
            self._dir / self.lock_file,
            stale_s=LOCK_STALE_S,
            now=time.time,
            owner=f"pid {os.getpid()}\nstarted {now()}\n",
        )
        try:
            return self._run(reason, lock)
        finally:
            lock.release()

    def _run(self, reason: str, lock: HeldLock) -> dict[str, Any]:
        started = now()
        outcome: dict[str, Any] = {"started_at": started, "reason": reason, "ok": False, "run": None}
        try:
            previous = (read_status(self._dir, self.status_file) or {}).get("last_run")
            self._write_status({"state": "running", "started_at": started, "reason": reason, "last_run": previous})
            release = self.find_release()
            outcome["run"] = release.id
            dumps = self._dir / self.dump_dir
            self._drop_other_releases(dumps, release)
            files = [
                self._downloader.download(
                    dump.url, dumps, digest=dump.digest, size=dump.size, progress=lambda _: lock.refresh()
                )
                for dump in release.files
            ]
            meta = self.build(files)
            for path in files:  # a verified dump could be reused, but hundreds of MB are not worth keeping
                path.unlink(missing_ok=True)
        except BaseException as exc:
            # A stopped container (KeyboardInterrupt from stop_on_sigterm) is no failure of the source: ok stays open
            failed = {"ok": False if isinstance(exc, Exception) else None, "error": str(exc) or type(exc).__name__}
            self._write_status({"state": "idle", "last_run": {**outcome, **failed, "finished_at": now()}})
            raise
        summary = self.summary(meta)
        last = {**outcome, "ok": True, "finished_at": now(), **summary}
        self._write_status({"state": "idle", "last_run": {**last, "error": None}})
        log.info("%s index built from release %s (%s): %s", self.label, release.id, reason or "asked", summary)
        return meta

    def record_check(self, newest: Release | None = None, error: BaseException | None = None) -> None:
        """A check that found nothing to build, or failed, goes to the status like a run (reason ``check``): a failed
        one so the gauge and its alert see it, a good one so that an earlier failure no longer counts. ``newest`` is
        the release the source offered, when it was asked. While a run holds the lock the check writes nothing: the
        run is under way and writes its own outcome."""
        try:
            lock = acquire_lock(
                self._dir / self.lock_file, stale_s=LOCK_STALE_S, now=time.time, owner=f"pid {os.getpid()}\ncheck\n"
            )
        except LockHeldError:
            return
        try:
            stamp = now()
            outcome = {
                "started_at": stamp,
                "reason": "check",
                "ok": error is None,
                "run": newest.id if newest else None,
            }
            failure = None if error is None else f"check: {str(error) or type(error).__name__}"
            self._write_status({"state": "idle", "last_run": {**outcome, "finished_at": stamp, "error": failure}})
        finally:
            lock.release()

    def _drop_other_releases(self, dumps: Path, release: Release) -> None:
        """Remove what an older release left behind (a ``.part`` it never finished); the files of ``release`` resume."""
        if not dumps.is_dir():
            return
        keep = {name for dump in release.files for name in (dump.name, dump.name + PART_SUFFIX)}
        for leftover in dumps.iterdir():
            if leftover.is_file() and leftover.name not in keep:
                leftover.unlink(missing_ok=True)

    def _write_status(self, status: dict[str, Any]) -> None:
        atomic_write_text(self._dir / self.status_file, json.dumps({"updated_at": now(), **status}, indent=2))
