"""ZIM sync job (PLAN.md 4.1): adopt local files, prune, download updates, switch ``active.json``, prune.

Runs in the updater sidecar (``compendium zim sync --loop``) or by hand; the API never downloads.
Every successful activation is written at once, so an interrupted run leaves a valid state and
the next run continues where it stopped (the downloader resumes ``.part`` files). One run at a time:
two would download into the same ``.part`` file and overwrite each other's ``active.json``.

What may go goes before anything comes, and a download waits for room (audit 2026-09-28, BE-12): a retired archive
was deleted only by a run after its retention, the loop ran next after ZIM_SYNC_INTERVAL and downloaded first, and
the next update put three Wikipedia generations, about 41 GB, on a volume sized for two. A run that retires an
archive names when it may go, and the loop comes back then. ``active.json`` is written only when it changes: every
write made every API worker reopen every archive and lose its caches (PE-08).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.jobs.lock import HeldLock, LockHeldError, acquire_lock
from app.settings import Settings
from app.sources.zim.active import (
    ACTIVE_FILE,
    ActiveArchive,
    ActiveState,
    RetiredArchive,
    atomic_write_text,
    read_active,
    write_active,
)
from app.sources.zim.archive import ZimArchive, dump_date
from app.sources.zim.catalog import OPDS_DEFAULT_URL, CatalogEntry, KiwixCatalog, Metalink
from app.sources.zim.downloader import (
    DEFAULT_ALLOWED_HOSTS,
    PART_SUFFIX,
    Downloader,
    DownloadError,
    DownloadProgress,
    TransferError,
    check_download_url,
)
from app.sources.zim.subscriptions import Subscription, SubscriptionManifest, load_manifest

log = logging.getLogger(__name__)

STATUS_FILE = "sync_status.json"
TRIGGER_FILE = "sync.request"
ALIVE_FILE = "sync_alive"  # the sign of life of the updater loop (app/jobs/runner.py)
LOCK_FILE = "sync.lock"
# A run writes its status at every step and every second of a download, and each write refreshes the lock;
# an hour without a sign of life means the run crashed.
LOCK_STALE_S = 3600
# Room a download leaves besides the archive: on a small host state, Prometheus and the logs share the volume's disk
FREE_SPACE_MARGIN = 1_000_000_000
# A retired archive that could not go when due (a file Windows keeps open) is tried again after this, not at once
PRUNE_RETRY = timedelta(hours=1)


class SyncRunningError(RuntimeError):
    """Another sync holds the lock file in the ZIM directory."""


class CatalogLike(Protocol):
    def latest(self, name: str, flavour: str) -> CatalogEntry | None: ...

    def metalink(self, url: str, *, check: Callable[[str], None] | None = None) -> Metalink: ...


class DownloaderLike(Protocol):
    def download(
        self,
        url: str,
        target_dir: Path,
        *,
        digest: str,
        size: int,
        progress: Callable[[DownloadProgress], None] | None = None,
    ) -> Path: ...


@dataclass(frozen=True)
class SyncOptions:
    profile: str
    download_missing: bool = False


@dataclass
class SyncReport:
    profile: str
    started_at: str
    finished_at: str = ""
    adopted: list[str] = field(default_factory=list)
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)  # files this run retired: replaced, or of another profile (KO-21)
    errors: list[str] = field(default_factory=list)
    # An error a run soon after can fix cheaply: resume a .part, reach the catalog again (not a hash mismatch)
    retry_soon: bool = False
    stopped: bool = False  # the container stopped the run; the next start resumes it (no error, audit KO-13)
    next_prune_at: str = ""  # when the first retired archive may go; the loop runs again then (BE-12)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_status(zim_dir: Path) -> dict[str, Any] | None:
    """Last sync status written by the job, or ``None`` when there is none (or it is unreadable)."""
    path = Path(zim_dir) / STATUS_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("cannot read %s: %s", path, exc)
        return None
    if not isinstance(data, dict):  # every reader expects the object the job writes
        log.warning("%s holds no JSON object; ignored", path)
        return None
    return data


def _finished_run(status: dict[str, Any] | None) -> dict[str, Any] | None:
    """The report of the last run that finished, from a status file written by any earlier run."""
    if status is None:
        return None
    run = status.get("last_run")
    if isinstance(run, dict) and run.get("finished_at"):
        return run
    earlier = status.get("last_finished")
    return earlier if isinstance(earlier, dict) else None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _free_bytes(directory: Path) -> int:
    return shutil.disk_usage(directory).free


class ZimSync:
    """One sync run over the subscriptions of a profile; state lives in the ZIM directory."""

    def __init__(
        self,
        zim_dir: Path,
        manifest: SubscriptionManifest,
        catalog: CatalogLike | None,
        downloader: DownloaderLike,
        *,
        clock: Callable[[], datetime] = _utcnow,
        retention: timedelta = timedelta(hours=24),
        allowed_hosts: Sequence[str] = DEFAULT_ALLOWED_HOSTS,
        free_bytes: Callable[[Path], int] = _free_bytes,
    ) -> None:
        self._zim_dir = Path(zim_dir)
        self._manifest = manifest
        self._catalog = catalog
        self._downloader = downloader
        self._clock = clock
        self._retention = retention
        self._allowed_hosts = tuple(allowed_hosts)
        self._free_bytes = free_bytes
        self._written: dict[str, Any] | None = None  # the state as active.json holds it, without its time stamp
        self._report: SyncReport | None = None
        self._last_finished: dict[str, Any] | None = None
        self._lock: HeldLock | None = None

    def run(self, options: SyncOptions) -> SyncReport:
        """One run over the subscriptions; ``SyncRunningError`` while another run holds the lock."""
        try:
            self._lock = acquire_lock(
                self._zim_dir / LOCK_FILE,
                stale_s=LOCK_STALE_S,
                now=lambda: self._clock().timestamp(),
                owner=f"pid {os.getpid()}\nstarted {self._clock().isoformat()}\n",
            )
        except LockHeldError as exc:
            raise SyncRunningError(
                f"Ein ZIM-Sync läuft bereits ({exc.path.name}, letztes Lebenszeichen vor {exc.age_s:.0f} s)"
            ) from None
        try:
            return self._run(options)
        finally:
            self._lock.release()
            self._lock = None

    def _run(self, options: SyncOptions) -> SyncReport:
        # The end and the errors of the last finished run stay in the status while this one runs; the age and
        # error alerts would otherwise lose their series for the length of every run
        self._last_finished = _finished_run(read_status(self._zim_dir))
        report = SyncReport(profile=options.profile, started_at=self._clock().isoformat())
        self._report = report
        self._write_status("running")
        try:
            state = self._load_state(options.profile)
            subscriptions = self._manifest.for_profile(options.profile)
            for sub in subscriptions:
                self._adopt(sub, state, report)
            self._prune(state, report)  # before any download: a retired archive past its retention goes first
            self._prune_partials(subscriptions, state, report)
            for sub in subscriptions:
                self._update(sub, state, options, report)
            self._retire_other_profiles(subscriptions, state, report)
            self._prune(state, report)  # what this run retired, with a retention of 0 at once
            self._prune_partials(subscriptions, state, report)
            report.next_prune_at = self._next_prune(state)
            if state.model_dump(exclude={"updated_at"}) != self._written or not (self._zim_dir / ACTIVE_FILE).exists():
                self._save(state)
        except BaseException as exc:  # also a full volume or Ctrl+C: the status must not stay "running"
            report.finished_at = self._clock().isoformat()
            if isinstance(exc, Exception):
                report.errors.append(f"Lauf abgebrochen: {type(exc).__name__}: {exc}")
                self._write_status("error")
            else:
                # A stopped container (KeyboardInterrupt from stop_on_sigterm) is no failure of the run: as in
                # DumpSync, it leaves the errors - and KompendiumZimSyncErrors - to what went wrong
                report.stopped = True
                self._write_status("idle")
            raise
        report.finished_at = self._clock().isoformat()
        self._write_status("idle")
        log.info(
            "zim sync %s: adopted %s, downloaded %s, skipped %s, missing %s, pruned %s, errors %d",
            options.profile,
            report.adopted,
            report.downloaded,
            report.skipped,
            report.missing,
            report.pruned,
            len(report.errors),
        )
        return report

    # -- steps -----------------------------------------------------------------------------------
    def _load_state(self, profile: str) -> ActiveState:
        try:
            state = read_active(self._zim_dir)
        except ValueError as exc:
            log.error("%s; rebuilding the state from local files", exc)
            state = None
        self._written = state.model_dump(exclude={"updated_at"}) if state is not None else None
        state = state or ActiveState()
        state.profile = profile
        return state

    def _adopt(self, sub: Subscription, state: ActiveState, report: SyncReport) -> None:
        """Register a local file that is not (or no longer) in the state; the newest dump wins, older ones retire.

        A state rebuilt after ``active.json`` was lost knows no retired dump, and the prune deletes only what the state
        lists: a generation retired before stayed on the volume for good (audit 2026-09-29, Q2).
        """
        current = state.archives.get(sub.id)
        if current is not None:
            if (self._zim_dir / current.file).exists():
                return
            log.warning("%s listed in active.json but missing on disk; dropping it", current.file)
            del state.archives[sub.id]
        candidates = [p for p in self._zim_dir.glob("*.zim") if sub.matches_file(p.name)]
        # the newest that opens: a newest file libzim cannot read decided alone and left none (audit 2026-09-28, KO-24)
        for path in sorted(candidates, key=lambda p: dump_date(p.name), reverse=True):
            try:
                state.archives[sub.id] = self._describe(path, sub)
            except Exception as exc:  # unreadable file: report it, try the next older one
                report.errors.append(f"{sub.id}: cannot open {path.name}: {exc}")
                continue
            retired = {archive.file for archive in state.retired}
            for older in sorted(candidates):  # a file without a dump date in its name is not the sync's to delete
                if dump_date(older.name) and dump_date(older.name) < dump_date(path.name) and older.name not in retired:
                    state.retired.append(RetiredArchive(file=older.name, retired_at=self._clock().isoformat()))
                    report.retired.append(older.name)
            self._save(state)
            report.adopted.append(sub.id)
            return

    def _update(self, sub: Subscription, state: ActiveState, options: SyncOptions, report: SyncReport) -> None:
        local = state.archives.get(sub.id)
        if self._catalog is None:
            if local is None:
                report.missing.append(sub.id)
            return
        try:
            remote = self._catalog.latest(sub.name, sub.flavour)
        except Exception as exc:  # the catalog is a remote system; one failure must not stop the run
            report.errors.append(f"{sub.id}: catalog lookup failed: {exc}")
            report.retry_soon = True
            return
        if remote is None:
            report.errors.append(f"{sub.id}: not offered by the catalog")
            return
        if local is not None and dump_date(local.file) >= remote.dump_date:
            report.skipped.append(sub.id)
            return
        if local is None and not options.download_missing:
            report.missing.append(sub.id)
            return
        if remote.file_name in state.unreadable:  # hash-checked and still unreadable: fetching it again changes nothing
            report.errors.append(f"{sub.id}: {remote.file_name} could not be opened; waiting for a newer dump")
            return
        try:
            check_download_url(remote.metalink_url, self._allowed_hosts)  # the hash must come from Kiwix too
            metalink = self._catalog.metalink(remote.metalink_url, check=self._check_url)
            check_download_url(metalink.source_url, self._allowed_hosts)  # also after redirects
            cramped = self._no_room_for(remote.download_url, metalink.size)
            if cramped:
                report.errors.append(f"{sub.id}: {cramped}")
                self._write_status("running")
                return
            path = self._downloader.download(
                remote.download_url,
                self._zim_dir,
                digest=metalink.sha256,
                size=metalink.size,
                progress=self._on_progress,
            )
        except (TransferError, httpx.HTTPError, OSError) as exc:  # network, full volume: the next run resumes
            report.errors.append(f"{sub.id}: {exc}")
            report.retry_soon = True
            self._write_status("running")
            return
        except (DownloadError, ValueError) as exc:  # refused or broken: fetching again soon would not help
            report.errors.append(f"{sub.id}: {exc}")
            self._write_status("running")
            return
        try:
            archive = self._describe(path, sub)
        except Exception as exc:  # libzim raises RuntimeError for a file it cannot read, e.g. a newer version
            # the hash matched, so every run would fetch the same unreadable file again (13.6 GB each, KO-24)
            report.errors.append(f"{sub.id}: cannot open the downloaded {path.name}, deleted it: {exc}")
            self._delete(path)
            state.unreadable.append(path.name)
            self._save(state)
            self._write_status("running")
            return
        if local is not None and local.file != archive.file:
            state.retired.append(RetiredArchive(file=local.file, retired_at=self._clock().isoformat()))
            report.retired.append(local.file)
        state.archives[sub.id] = archive
        state.unreadable = [name for name in state.unreadable if not sub.matches_file(name)]
        self._save(state)
        report.downloaded.append(sub.id)
        self._write_status("running")

    def _prune(self, state: ActiveState, report: SyncReport) -> None:
        """Delete retired files once the retention has passed; failures are retried next run."""
        now = self._clock()
        in_use = {a.file for a in state.archives.values()}
        keep: list[RetiredArchive] = []
        for retired in state.retired:
            if datetime.fromisoformat(retired.retired_at) + self._retention > now:
                keep.append(retired)
                continue
            path = self._zim_dir / retired.file
            if retired.file not in in_use and path.exists():
                try:
                    path.unlink()
                except OSError as exc:
                    log.warning("cannot delete %s yet: %s", path.name, exc)
                    keep.append(retired)
                    continue
            report.pruned.append(retired.file)
        state.retired = keep

    def _prune_partials(self, subscriptions: Sequence[Subscription], state: ActiveState, report: SyncReport) -> None:
        """Delete ``.part`` files of dumps no newer than the active one: no run will resume them (up to 14 GB each).

        Files of other profiles' subscriptions and of newer dumps stay; a newer one is resumed by the next run.
        """
        for part in sorted(self._zim_dir.glob(f"*.zim{PART_SUFFIX}")):
            target = part.name.removesuffix(PART_SUFFIX)
            sub = next((s for s in subscriptions if s.matches_file(target)), None)
            active = state.archives.get(sub.id) if sub is not None else None
            if active is None or not dump_date(target) or dump_date(target) > dump_date(active.file):
                continue
            try:
                part.unlink()
            except OSError as exc:
                log.warning("cannot delete %s yet: %s", part.name, exc)
                continue
            report.pruned.append(part.name)

    def _retire_other_profiles(
        self, subscriptions: Sequence[Subscription], state: ActiveState, report: SyncReport
    ) -> None:
        """Retire the archives no subscription of this profile names, once its required ones are active.

        After a change of ZIM_PROFILE they stayed active for good: the full Wikipedia went on leading after standard ->
        compact, and its 13.6 GB never went (audit 2026-09-28, KO-21). Until the new profile has its required
        archives, the old ones serve.
        """
        if not {sub.id for sub in subscriptions if sub.required} <= set(state.archives):
            return
        wanted = {sub.id for sub in subscriptions}
        for archive_id in [archive_id for archive_id in state.archives if archive_id not in wanted]:
            archive = state.archives.pop(archive_id)
            state.retired.append(RetiredArchive(file=archive.file, retired_at=self._clock().isoformat()))
            report.retired.append(archive.file)

    def due_in(self, report: SyncReport) -> timedelta | None:
        """How long until a retired archive of the run may go, at least ``PRUNE_RETRY``; ``None`` when none waits."""
        if not report.next_prune_at:
            return None
        return max(datetime.fromisoformat(report.next_prune_at) - self._clock(), PRUNE_RETRY)

    # -- helpers ---------------------------------------------------------------------------------
    def _next_prune(self, state: ActiveState) -> str:
        due = [datetime.fromisoformat(retired.retired_at) + self._retention for retired in state.retired]
        return min(due).isoformat() if due else ""

    def _no_room_for(self, url: str, size: int) -> str:
        """Why the download of ``url`` would not fit, or "": what its ``.part`` already holds counts."""
        part = self._zim_dir / f"{url.rsplit('/', 1)[-1]}{PART_SUFFIX}"
        needed = size - (part.stat().st_size if part.exists() else 0) + FREE_SPACE_MARGIN
        free = self._free_bytes(self._zim_dir)
        if free >= needed:
            return ""
        return f"{free / 1e9:.1f} GB free, {needed / 1e9:.1f} GB needed for {part.name.removesuffix(PART_SUFFIX)}"

    def _save(self, state: ActiveState) -> None:
        state.updated_at = self._clock().isoformat()
        write_active(self._zim_dir, state)
        self._written = state.model_dump(exclude={"updated_at"})

    @staticmethod
    def _delete(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:  # the next adoption skips it as unreadable; an operator removes it
            log.warning("cannot delete %s: %s", path.name, exc)

    def _check_url(self, url: str) -> None:
        check_download_url(url, self._allowed_hosts)

    def _describe(self, path: Path, sub: Subscription) -> ActiveArchive:
        archive = ZimArchive(path)  # open only long enough to read the metadata
        return ActiveArchive(
            id=sub.id,
            file=path.name,
            uuid=archive.uuid,
            date=archive.date,
            project=archive.project if archive.project != "other" else sub.project,
            size=path.stat().st_size,
            activated_at=self._clock().isoformat(),
        )

    def _on_progress(self, progress: DownloadProgress) -> None:
        self._write_status(
            "running",
            {
                "file": progress.file_name,
                "percent": progress.percent,
                "bytes_done": progress.bytes_done,
                "bytes_total": progress.bytes_total,
                "speed_mb_s": round(progress.speed_bytes_s / 1_000_000, 2),
            },
        )

    def _write_status(self, state: str, download: dict[str, Any] | None = None) -> None:
        payload = {
            "state": state,
            "updated_at": self._clock().isoformat(),
            "last_run": self._report.to_dict() if self._report else None,
            "last_finished": self._last_finished,
            "download": download,
        }
        try:
            atomic_write_text(self._zim_dir / STATUS_FILE, json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError as exc:
            log.warning("cannot write %s: %s", STATUS_FILE, exc)
        if self._lock is not None:
            try:
                self._lock.refresh()  # sign of life: a lock older than LOCK_STALE_S counts as abandoned
            except OSError as exc:
                log.warning("cannot refresh %s: %s", LOCK_FILE, exc)


def build_sync(settings: Settings, *, offline: bool = False) -> ZimSync:
    """Wire the job from settings: manifest, Kiwix catalog (unless offline) and downloader."""
    manifest = load_manifest(settings.zim_manifest_path)
    catalog = None if offline else KiwixCatalog(settings.zim_catalog_url or OPDS_DEFAULT_URL)
    downloader = Downloader(allowed_hosts=settings.zim_download_host_list)
    return ZimSync(
        settings.zim_dir,
        manifest,
        catalog,
        downloader,
        retention=timedelta(hours=settings.zim_retention_hours),
        allowed_hosts=settings.zim_download_host_list,
    )
