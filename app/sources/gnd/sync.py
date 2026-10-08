"""Keep the local GND index (D65) in step with the DNB's releases of its dumps.

The DNB publishes the GND as dumps twice a year or so (data.dnb.de/opendata, CC0) and lists every file with its
SHA-256 in ``001_Pruefsumme_Checksum.txt``, the version in the file name (``…_lds_20260217.ttl.gz``). The
``gnd-updater`` sidecar (``compendium gnd sync --loop``) builds the index when it is missing or unusable, when a newer
release with both dumps is out, or when forced. A run downloads the subject headings and the places as Turtle (about
65 MB, held to the published SHA-256), builds the index next to the old one and swaps it (``DumpSync``); the service
opens the new file by itself (``GndIndex``). Only the dumps are fetched: the service looks nothing up online.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.settings import Settings
from app.sources.dump_sync import DumpFile, DumpSync, Release, ReleaseNotFoundError
from app.sources.dump_sync import read_status as read_dump_status
from app.sources.gnd.index import GndIndex, build_gnd_index
from app.sources.zim.catalog import USER_AGENT
from app.sources.zim.downloader import Downloader, check_download_url

log = logging.getLogger(__name__)

DUMPS_URL = "https://data.dnb.de/opendata"
CHECKSUM_FILE = "001_Pruefsumme_Checksum.txt"
DUMP_DIR = "gnd_dumps"
STATUS_FILE = "gnd_status.json"
LOCK_FILE = "gnd_sync.lock"
ALIVE_FILE = "gnd_alive"  # the sign of life of the sync loop (app/jobs/runner.py)
KINDS = (("sachbegriff", "Sachbegriff"), ("geografikum", "Geografikum"))  # the file's name and the record's kind
_LINE_RE = re.compile(r"^([0-9a-f]{64})\s+(authorities-gnd-(sachbegriff|geografikum)_lds_(\d{8})\.ttl\.gz)$")


class GndSyncError(ReleaseNotFoundError):
    """The DNB offers no release with both dumps to build from."""


def find_release(client: httpx.Client, base_url: str = DUMPS_URL) -> Release:
    """The newest release whose subject and place dumps are both out, with their SHA-256 and sizes."""
    base = base_url.rstrip("/")
    # The checksum file carries the digests the downloads are held to: https, one host, and no redirect to another
    check_download_url(f"{base}/{CHECKSUM_FILE}", (httpx.URL(base).host,))
    response = client.get(f"{base}/{CHECKSUM_FILE}", follow_redirects=False)
    response.raise_for_status()
    versions: dict[str, dict[str, tuple[str, str]]] = {}
    for line in response.text.splitlines():
        if (match := _LINE_RE.match(line.strip())) is not None:
            digest, name, kind, version = match.groups()
            versions.setdefault(version, {})[kind] = (name, digest)
    for version in sorted(versions, reverse=True):
        found = versions[version]
        if all(kind in found for kind, _ in KINDS):
            files = tuple(_dump_file(client, base, *found[kind]) for kind, _ in KINDS)
            return Release(version, datetime.strptime(version, "%Y%m%d").date(), files)
    raise GndSyncError(f"no GND release on {base} has both the subject and the place dump")


def _dump_file(client: httpx.Client, base: str, name: str, digest: str) -> DumpFile:
    """The file with the size the server announces; the checksum file names no sizes."""
    head = client.head(f"{base}/{name}", follow_redirects=False)
    head.raise_for_status()
    size = head.headers.get("content-length", "")
    if not size.isdigit() or int(size) == 0:
        raise GndSyncError(f"{name}: the server announces no size")
    return DumpFile(name, f"{base}/{name}", int(size), digest)


def _day(text: object) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def read_status(state_dir: Path) -> dict[str, Any] | None:
    """The GND sync's status file, ``None`` without one or when it cannot be read."""
    return read_dump_status(state_dir, STATUS_FILE)


class GndSync(DumpSync):
    """Decide whether the GND index at ``index_path`` needs building, and build it from the newest release."""

    status_file = STATUS_FILE
    lock_file = LOCK_FILE
    dump_dir = DUMP_DIR
    label = "GND"

    def __init__(self, index_path: Path, *, client: httpx.Client, base_url: str = DUMPS_URL) -> None:
        host = httpx.URL(base_url).host
        downloader = Downloader(client=client, allowed_hosts=(host,), suffixes=(".ttl.gz",), hash_name="sha256")
        super().__init__(index_path, client=client, base_url=base_url, downloader=downloader)

    def find_release(self) -> Release:
        return find_release(self._client, self.base_url)

    def build(self, files: list[Path]) -> dict[str, Any]:
        return build_gnd_index(list(zip(files, [kind for _, kind in KINDS], strict=True)), self.index_path)

    def summary(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {"release": meta["release"], "records": meta["records"]}

    def due(self, *, force: bool = False) -> str | None:
        """Why the index has to be built, or ``None``; asks the DNB's checksum file whether a newer release is out."""
        if force:
            return "forced"
        if not self.index_path.is_file():
            return "no index"
        index = GndIndex(self.index_path)
        try:
            if not index.available or not index.intact():  # a broken page is found here, not by a request
                return "index unusable"
            built_from = _day(index.meta().get("release"))
        finally:
            index.close()
        try:
            newest = self.find_release()
        except Exception as exc:  # recorded like a failed run, so the gauge and its alert see it
            self.record_check(error=exc)
            raise
        # An index built by hand from undated files has no release: the newest one replaces it
        if built_from is None or newest.date > built_from:
            return "newer release"
        self.record_check(newest)
        return None


def build_gnd_sync(settings: Settings) -> GndSync:
    """The sync of this installation: the GND index of the settings, the DNB's opendata folder or a mirror."""
    client = httpx.Client(timeout=60.0, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    return GndSync(settings.gnd_db_path, client=client, base_url=settings.gnd_dumps_url)
