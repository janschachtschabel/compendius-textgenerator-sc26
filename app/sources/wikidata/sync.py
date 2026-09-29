"""Keep the local Wikidata index (D43) in step with the archives: fetch three dumps of the German Wikipedia, build it.

A new installation has no index, and an index older than the active Wikipedia archive lacks the numbers of the
archive's new articles (D64). The ``wikidata-updater`` sidecar (``compendium wikidata sync --loop``) builds the index
when it is missing or unusable, when the active Wikipedia archive is dated after the dump the index was built from
and dumps.wikimedia.org has a newer run, or when forced. A run takes the newest run of dewiki whose ``page_props``,
``page`` and ``langlinks`` tables are done, downloads them (about 750 MB, checked against the SHA-1 Wikimedia
publishes), builds the index next to the old one and swaps it (``DumpSync``); the service opens the new file by itself
(``WikidataIndex``). ``langlinks`` gives each article's English title, which names its DBpedia resource (D65).

Only the dump files are fetched, nothing is asked of Wikidata itself: the service still looks nothing up online.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.jobs.dump_sync import DumpFile, DumpSync, Release, ReleaseNotFoundError
from app.jobs.dump_sync import read_status as read_dump_status
from app.settings import Settings
from app.sources.wikidata.index import WikidataIndex, build_index
from app.sources.zim.active import read_active
from app.sources.zim.archive import dump_date
from app.sources.zim.catalog import USER_AGENT
from app.sources.zim.downloader import Downloader, check_download_url

log = logging.getLogger(__name__)

DUMPS_URL = "https://dumps.wikimedia.org"
WIKI = "dewiki"
DUMP_DIR = "wikidata_dumps"
STATUS_FILE = "wikidata_status.json"
LOCK_FILE = "wikidata_sync.lock"
ALIVE_FILE = "wikidata_alive"  # the sign of life of the sync loop (app/jobs/runner.py)
RUNS_ASKED = 4  # the newest runs whose status is read; a run older than that is not worth an index
_RUN_RE = re.compile(r'href="(\d{8})/"')
_JOBS = (("page_props", "pagepropstable"), ("page", "pagetable"), ("langlinks", "langlinkstable"))


class WikidataSyncError(ReleaseNotFoundError):
    """dumps.wikimedia.org offers no run to build from."""


@dataclass(frozen=True)
class DumpRun(Release):
    """A run of the German Wikipedia's dumps, its files in this order: ``page_props``, ``page``, ``langlinks``."""

    @property
    def page_props(self) -> DumpFile:
        return self.files[0]

    @property
    def page(self) -> DumpFile:
        return self.files[1]

    @property
    def langlinks(self) -> DumpFile:
        return self.files[2]


def find_run(client: httpx.Client, base_url: str = DUMPS_URL) -> DumpRun:
    """The newest run of the German Wikipedia whose ``page_props``, ``page`` and ``langlinks`` tables are done."""
    base = base_url.rstrip("/")
    # The run list and dumpstatus.json carry the checksums the downloads are held to: https, one host, and no
    # redirect to another (a redirect is an error here; the downloads may follow one, their hash anchors them)
    check_download_url(f"{base}/{WIKI}/", (httpx.URL(base).host,))
    listing = client.get(f"{base}/{WIKI}/", follow_redirects=False)
    listing.raise_for_status()
    for run_id in sorted(set(_RUN_RE.findall(listing.text)), reverse=True)[:RUNS_ASKED]:
        response = client.get(f"{base}/{WIKI}/{run_id}/dumpstatus.json", follow_redirects=False)
        if response.status_code == 404:  # a run that has only just been started
            continue
        response.raise_for_status()
        try:
            status = response.json()
        except ValueError as exc:  # a garbled answer is the site's hiccup, not a dump the build cannot read
            raise WikidataSyncError(f"dumpstatus.json of run {run_id} is unreadable: {exc}") from exc
        files = _done_files(status, base, run_id)
        if files is not None:
            return DumpRun(run_id, datetime.strptime(run_id, "%Y%m%d").date(), files)
    raise WikidataSyncError(f"no run of {WIKI} on {base} has page_props, page and langlinks done")


def _done_files(status: Any, base: str, run_id: str) -> tuple[DumpFile, ...] | None:
    """The files of a run when all its jobs are done; the path of each is joined to the host asked, never another."""
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
    return tuple(found)


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
    """The Wikidata sync's status file, ``None`` without one or when it cannot be read."""
    return read_dump_status(state_dir, STATUS_FILE)


class WikidataSync(DumpSync):
    """Decide whether the index at ``index_path`` needs building, and build it from the newest finished run."""

    status_file = STATUS_FILE
    lock_file = LOCK_FILE
    dump_dir = DUMP_DIR
    label = "Wikidata"

    def __init__(
        self,
        index_path: Path,
        *,
        client: httpx.Client,
        base_url: str = DUMPS_URL,
        archive_date: Callable[[], date | None] = lambda: None,
    ) -> None:
        host = httpx.URL(base_url).host
        downloader = Downloader(client=client, allowed_hosts=(host,), suffixes=(".sql.gz",), hash_name="sha1")
        super().__init__(index_path, client=client, base_url=base_url, downloader=downloader)
        self.archive_date = archive_date

    def find_release(self) -> DumpRun:
        return find_run(self._client, self.base_url)

    def build(self, files: list[Path]) -> dict[str, Any]:
        page_props, page, langlinks = files
        return build_index(page_props, page, self.index_path, langlinks=langlinks)

    def summary(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {"dump": meta["dump"], "articles": meta["articles"], "english": meta["english"]}

    def due(self, *, force: bool = False) -> str | None:
        """Why the index has to be built, or ``None``; asks dumps.wikimedia.org only when the archive is newer."""
        if force:
            return "forced"
        if not self.index_path.is_file():
            return "no index"
        index = WikidataIndex(self.index_path)
        try:
            if not index.available or not index.intact():  # a broken page is found here, not by a request
                return "index unusable"
            built_from = _day(index.meta().get("dump"))
        finally:
            index.close()
        archive = self.archive_date()
        if archive is None or built_from is None or archive <= built_from:
            self.record_check()
            return None
        # The archive has articles the index may lack; only a run after the index's dump can bring them. A check that
        # fails goes to the status like a failed run: the index falls behind the archive until it succeeds
        try:
            newest = find_run(self._client, self.base_url)
        except Exception as exc:
            self.record_check(error=exc)
            raise
        if newest.date > built_from:
            return "archive newer than the index"
        self.record_check(newest)
        return None


def build_sync(settings: Settings) -> WikidataSync:
    """The sync of this installation: the index of the settings, the archive date the service's archives carry."""
    client = httpx.Client(timeout=60.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    return WikidataSync(
        settings.wikidata_db_path,
        client=client,
        base_url=settings.wikidata_dumps_url,
        archive_date=lambda: active_wikipedia_date(settings.zim_dir, settings.zim_path_list),
    )
