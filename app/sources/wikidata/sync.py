"""Keep the local Wikidata index (D43) in step with the archives: fetch two dumps of the German Wikipedia, build it.

A new installation has no index, and an index older than the active Wikipedia archive lacks the numbers of the
archive's new articles (D64). The ``wikidata-updater`` sidecar (``compendium wikidata sync --loop``) builds the index
when it is missing or unusable, when the active Wikipedia archive is dated after the dump the index was built from
and dumps.wikimedia.org has a newer run, or when forced. A run takes the newest run of dewiki whose ``page_props``
and ``page`` tables are done, downloads both (about 420 MB, checked against the SHA-1 Wikimedia publishes), builds the
index next to the old one and swaps it; the service opens the new file by itself (``WikidataIndex``). The dumps are
removed after a build; a download cut short stays as ``.part`` for the next run.

Only the dump files are fetched, nothing is asked of Wikidata itself: the service still looks nothing up online.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.jobs.lock import acquire_lock
from app.settings import Settings
from app.sources.wikidata.index import WikidataIndex, build_index
from app.sources.zim.active import atomic_write_text, read_active
from app.sources.zim.archive import dump_date
from app.sources.zim.catalog import USER_AGENT
from app.sources.zim.downloader import Downloader, check_download_url

log = logging.getLogger(__name__)

DUMPS_URL = "https://dumps.wikimedia.org"
WIKI = "dewiki"
DUMP_DIR = "wikidata_dumps"
STATUS_FILE = "wikidata_status.json"
LOCK_FILE = "wikidata_sync.lock"
LOCK_STALE_S = 3 * 3600  # a run downloads 420 MB and builds for 5 to 15 minutes; hours of silence mean it crashed
RUNS_ASKED = 4  # the newest runs whose status is read; a run older than that is not worth an index
_RUN_RE = re.compile(r'href="(\d{8})/"')
_JOBS = (("page_props", "pagepropstable"), ("page", "pagetable"))


class WikidataSyncError(RuntimeError):
    """dumps.wikimedia.org offers no run to build from."""


@dataclass(frozen=True)
class DumpFile:
    name: str
    url: str
    size: int
    sha1: str


@dataclass(frozen=True)
class DumpRun:
    id: str  # the run's directory, "20260901"
    date: date
    page_props: DumpFile
    page: DumpFile


def find_run(client: httpx.Client, base_url: str = DUMPS_URL) -> DumpRun:
    """The newest run of the German Wikipedia whose ``page_props`` and ``page`` tables are done."""
    base = base_url.rstrip("/")
    # The run list and dumpstatus.json carry the checksums the downloads are held to: https and one host, as for them
    check_download_url(f"{base}/{WIKI}/", (httpx.URL(base).host,))
    listing = client.get(f"{base}/{WIKI}/")
    listing.raise_for_status()
    for run_id in sorted(set(_RUN_RE.findall(listing.text)), reverse=True)[:RUNS_ASKED]:
        response = client.get(f"{base}/{WIKI}/{run_id}/dumpstatus.json")
        if response.status_code == 404:  # a run that has only just been started
            continue
        response.raise_for_status()
        files = _done_files(response.json(), base, run_id)
        if files is not None:
            return DumpRun(run_id, datetime.strptime(run_id, "%Y%m%d").date(), *files)
    raise WikidataSyncError(f"no run of {WIKI} on {base} has page_props and page done")


def _done_files(status: Any, base: str, run_id: str) -> tuple[DumpFile, DumpFile] | None:
    """Both files of a run when both jobs are done; the path of each is joined to the host asked, never another."""
    jobs = status.get("jobs", {}) if isinstance(status, dict) else {}
    found = []
    for table, job_name in _JOBS:
        job = jobs.get(job_name) or {}
        name = f"{WIKI}-{run_id}-{table}.sql.gz"
        meta = (job.get("files") or {}).get(name) or {}
        path = str(meta.get("url") or "")
        if job.get("status") != "done" or not path.startswith(f"/{WIKI}/{run_id}/") or not meta.get("sha1"):
            return None
        found.append(DumpFile(name, base + path, int(meta["size"]), str(meta["sha1"])))
    return found[0], found[1]


def _day(text: object) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def active_wikipedia_date(zim_dir: Path, zim_paths: Sequence[Path] = ()) -> date | None:
    """The date of the Wikipedia archive the service reads: its ZIM date from ``active.json``, or with ``ZIM_PATHS``
    (the development setup, which has no active.json) the month in the file name."""
    if zim_paths:
        months = [dump_date(Path(path).name) for path in zim_paths if Path(path).name.startswith("wikipedia_")]
        return max((date.fromisoformat(f"{month}-01") for month in months if month), default=None)
    try:
        state = read_active(zim_dir)
    except ValueError as exc:
        log.warning("active.json in %s is unreadable: %s", zim_dir, exc)
        return None
    if state is None:
        return None
    days = [_day(archive.date) for archive in state.archives.values() if archive.project == "wikipedia"]
    return max((day for day in days if day is not None), default=None)


def read_status(state_dir: Path) -> dict[str, Any] | None:
    """The sync's status file, ``None`` without one or when it cannot be read."""
    path = Path(state_dir) / STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("%s is unreadable: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class WikidataSync:
    """Decide whether the index at ``index_path`` needs building, and build it from the newest finished run."""

    def __init__(
        self,
        index_path: Path,
        *,
        client: httpx.Client,
        base_url: str = DUMPS_URL,
        archive_date: Callable[[], date | None] = lambda: None,
    ) -> None:
        self.index_path = Path(index_path)
        self._dir = self.index_path.parent
        self._client = client
        self._base_url = base_url
        self._archive_date = archive_date
        host = httpx.URL(base_url).host
        self._downloader = Downloader(client=client, allowed_hosts=(host,), suffixes=(".sql.gz",), hash_name="sha1")

    def due(self, *, force: bool = False) -> str | None:
        """Why the index has to be built, or ``None``; asks dumps.wikimedia.org only when the archive is newer."""
        if force:
            return "forced"
        if not self.index_path.is_file():
            return "no index"
        index = WikidataIndex(self.index_path)
        try:
            if not index.available:
                return "index unusable"
            built_from = _day(index.meta().get("dump"))
        finally:
            index.close()
        archive = self._archive_date()
        if archive is None or built_from is None or archive <= built_from:
            return None
        # The archive has articles the index may lack; only a run after the index's dump can bring them
        newest = find_run(self._client, self._base_url)
        return "archive newer than the index" if newest.date > built_from else None

    def run(self, reason: str = "") -> dict[str, Any]:
        """Download the newest finished run, build the index and swap it in; the old index stays on any failure."""
        lock = acquire_lock(
            self._dir / LOCK_FILE, stale_s=LOCK_STALE_S, now=time.time, owner=f"pid {os.getpid()}\nstarted {_now()}\n"
        )
        started = _now()
        previous = (read_status(self._dir) or {}).get("last_run")
        self._write_status({"state": "running", "started_at": started, "reason": reason, "last_run": previous})
        outcome: dict[str, Any] = {"started_at": started, "reason": reason, "ok": False, "run": None}
        try:
            run = find_run(self._client, self._base_url)
            outcome["run"] = run.id
            dumps = self._dir / DUMP_DIR
            self._drop_other_runs(dumps, run)
            page_props, page = (
                self._downloader.download(dump.url, dumps, digest=dump.sha1, size=dump.size)
                for dump in (run.page_props, run.page)
            )
            meta = build_index(page_props, page, self.index_path)
        except Exception as exc:
            self._write_status({"state": "idle", "last_run": {**outcome, "finished_at": _now(), "error": str(exc)}})
            raise
        finally:
            lock.release()
        for path in (page_props, page):  # a verified dump could be reused, but 420 MB are not worth keeping
            path.unlink(missing_ok=True)
        last = {**outcome, "ok": True, "finished_at": _now(), "dump": meta["dump"], "articles": meta["articles"]}
        self._write_status({"state": "idle", "last_run": {**last, "error": None}})
        log.info("Wikidata index built from run %s (%s): %d articles", run.id, reason or "asked", meta["articles"])
        return meta

    def _drop_other_runs(self, dumps: Path, run: DumpRun) -> None:
        """Remove what an older run left behind (a ``.part`` it never finished); the files of ``run`` resume."""
        if not dumps.is_dir():
            return
        for leftover in dumps.iterdir():
            if leftover.is_file() and not leftover.name.startswith(f"{WIKI}-{run.id}-"):
                leftover.unlink(missing_ok=True)

    def _write_status(self, status: dict[str, Any]) -> None:
        atomic_write_text(self._dir / STATUS_FILE, json.dumps({"updated_at": _now(), **status}, indent=2))


def build_sync(settings: Settings) -> WikidataSync:
    """The sync of this installation: the index of the settings, the archive date the service's archives carry."""
    client = httpx.Client(timeout=60.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    return WikidataSync(
        settings.wikidata_db_path,
        client=client,
        base_url=settings.wikidata_dumps_url,
        archive_date=lambda: active_wikipedia_date(settings.zim_dir, settings.zim_path_list),
    )
