"""ZIM sync job (PLAN.md 4.1): adopt local files, download updates, switch ``active.json``, prune.

Runs in the updater sidecar (``compendium zim sync --loop``) or by hand; the API never downloads.
Every successful activation is written at once, so an interrupted run leaves a valid state and
the next run continues where it stopped (the downloader resumes ``.part`` files).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.settings import Settings
from app.sources.zim.active import (
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
    check_download_url,
)
from app.sources.zim.subscriptions import Subscription, SubscriptionManifest, load_manifest

log = logging.getLogger(__name__)

STATUS_FILE = "sync_status.json"
TRIGGER_FILE = "sync.request"


class CatalogLike(Protocol):
    def latest(self, name: str, flavour: str) -> CatalogEntry | None: ...

    def metalink(self, url: str) -> Metalink: ...


class DownloaderLike(Protocol):
    def download(
        self,
        url: str,
        target_dir: Path,
        *,
        sha256: str,
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
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_status(zim_dir: Path) -> dict[str, Any] | None:
    """Last sync status written by the job, or ``None`` when there is none (or it is unreadable)."""
    path = Path(zim_dir) / STATUS_FILE
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("cannot read %s: %s", path, exc)
        return None
    return data


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    ) -> None:
        self._zim_dir = Path(zim_dir)
        self._manifest = manifest
        self._catalog = catalog
        self._downloader = downloader
        self._clock = clock
        self._retention = retention
        self._allowed_hosts = tuple(allowed_hosts)
        self._report: SyncReport | None = None

    def run(self, options: SyncOptions) -> SyncReport:
        report = SyncReport(profile=options.profile, started_at=self._clock().isoformat())
        self._report = report
        self._write_status("running")
        try:
            state = self._load_state(options.profile)
            subscriptions = self._manifest.for_profile(options.profile)
            for sub in subscriptions:
                self._adopt(sub, state, report)
            for sub in subscriptions:
                self._update(sub, state, options, report)
            self._prune(state, report)
            self._prune_partials(subscriptions, state, report)
            state.updated_at = self._clock().isoformat()
            write_active(self._zim_dir, state)
        except BaseException as exc:  # also a full volume or Ctrl+C: the status must not stay "running"
            report.errors.append(f"Lauf abgebrochen: {type(exc).__name__}: {exc}")
            report.finished_at = self._clock().isoformat()
            self._write_status("error")
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
        state = state or ActiveState()
        state.profile = profile
        return state

    def _adopt(self, sub: Subscription, state: ActiveState, report: SyncReport) -> None:
        """Register a local file that is not (or no longer) in the state; the newest dump wins."""
        current = state.archives.get(sub.id)
        if current is not None:
            if (self._zim_dir / current.file).exists():
                return
            log.warning("%s listed in active.json but missing on disk; dropping it", current.file)
            del state.archives[sub.id]
        candidates = [p for p in self._zim_dir.glob("*.zim") if sub.matches_file(p.name)]
        if not candidates:
            return
        path = max(candidates, key=lambda p: dump_date(p.name))
        try:
            state.archives[sub.id] = self._describe(path, sub)
        except Exception as exc:  # unreadable file: report it, keep going
            report.errors.append(f"{sub.id}: cannot open {path.name}: {exc}")
            return
        write_active(self._zim_dir, state)
        report.adopted.append(sub.id)

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
        try:
            check_download_url(remote.metalink_url, self._allowed_hosts)  # the hash must come from Kiwix too
            metalink = self._catalog.metalink(remote.metalink_url)
            path = self._downloader.download(
                remote.download_url,
                self._zim_dir,
                sha256=metalink.sha256,
                size=metalink.size,
                progress=self._on_progress,
            )
            archive = self._describe(path, sub)
        except (DownloadError, httpx.HTTPError, ValueError, OSError) as exc:
            report.errors.append(f"{sub.id}: {exc}")
            self._write_status("running")
            return
        if local is not None and local.file != archive.file:
            state.retired.append(RetiredArchive(file=local.file, retired_at=self._clock().isoformat()))
        state.archives[sub.id] = archive
        write_active(self._zim_dir, state)
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

    # -- helpers ---------------------------------------------------------------------------------
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
            "download": download,
        }
        try:
            atomic_write_text(self._zim_dir / STATUS_FILE, json.dumps(payload, ensure_ascii=False, indent=2))
        except OSError as exc:
            log.warning("cannot write %s: %s", STATUS_FILE, exc)


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
