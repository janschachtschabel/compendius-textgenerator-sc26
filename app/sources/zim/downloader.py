"""Verified transfer of one ZIM file: range resume into a ``.part`` file, SHA-256 check, allowlist.

The downloader knows nothing about the catalog; the sync job hands it the URL plus the exact size
and hash from the metalink. Kiwix redirects to mirrors (verified 2026-09-17: 301 -> 302 -> 206),
so the allowlist applies to the URL we start from while integrity rests on the hash.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.sources.zim.catalog import USER_AGENT

log = logging.getLogger(__name__)

DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("download.kiwix.org", "lb.download.kiwix.org", "mirror.download.kiwix.org")
PART_SUFFIX = ".part"
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.zim$")


class DownloadError(RuntimeError):
    """Transfer or verification failed; the message says whether the ``.part`` file was kept."""


class _OversizedError(Exception):
    """Internal signal: the stream exceeded the size the metalink announced."""


def check_download_url(url: str, allowed_hosts: Collection[str]) -> None:
    """Raise ``DownloadError`` unless ``url`` is https and starts at an allowlisted host."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:  # not an httpx.HTTPError: it would abort the whole sync run
        raise DownloadError(f"invalid download URL {url!r}: {exc}") from exc
    if parsed.scheme != "https":
        raise DownloadError(f"download URL must use https: {url!r}")
    host = (parsed.host or "").lower()
    if host not in {allowed.lower() for allowed in allowed_hosts}:
        raise DownloadError(f"download host {host!r} is not in the allowlist {sorted(allowed_hosts)}")


def validate_file_name(name: str) -> str:
    """Accept plain ZIM file names only: no path parts, no hidden files, no other suffixes."""
    if not _FILE_NAME_RE.fullmatch(name) or ".." in name:
        raise ValueError(f"not a plain ZIM file name: {name!r}")
    return name


@dataclass
class DownloadProgress:
    file_name: str
    bytes_done: int
    bytes_total: int
    resumed_from: int
    started_at: float

    @property
    def percent(self) -> float:
        return round(100.0 * self.bytes_done / self.bytes_total, 1) if self.bytes_total else 0.0

    @property
    def speed_bytes_s(self) -> float:
        elapsed = max(time.monotonic() - self.started_at, 1e-6)
        return (self.bytes_done - self.resumed_from) / elapsed


ProgressCallback = Callable[[DownloadProgress], None]


@dataclass
class _Transfer:
    part: Path
    progress: DownloadProgress
    hasher: Any  # hashlib object; typeshed names it differently across versions


def _hash_file(path: Path, hasher: Any, chunk_size: int) -> None:
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            hasher.update(chunk)


class Downloader:
    def __init__(
        self,
        client: httpx.Client | None = None,
        allowed_hosts: Sequence[str] = DEFAULT_ALLOWED_HOSTS,
        chunk_size: int = 1 << 20,
        timeout: float = 60.0,
        progress_interval_s: float = 1.0,
    ) -> None:
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.chunk_size = chunk_size
        self.progress_interval_s = progress_interval_s
        self._client = client or httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )

    def close(self) -> None:
        self._client.close()

    def download(
        self, url: str, target_dir: Path, *, sha256: str, size: int, progress: ProgressCallback | None = None
    ) -> Path:
        """Fetch ``url`` into ``target_dir``, resuming a ``.part`` file; return the verified file path."""
        check_download_url(url, self.allowed_hosts)
        try:
            file_name = validate_file_name(url.rsplit("/", 1)[-1])
        except ValueError as exc:
            raise DownloadError(str(exc)) from exc
        directory = Path(target_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / file_name
        part = directory / f"{file_name}{PART_SUFFIX}"

        existing = part.stat().st_size if part.exists() else 0
        if existing > size:
            log.warning("%s is larger than the expected %d bytes; starting over", part.name, size)
            part.unlink()
            existing = 0
        transfer = _Transfer(
            part, DownloadProgress(file_name, existing, size, existing, time.monotonic()), hashlib.sha256()
        )
        if existing:
            log.info("%s: resuming at %d of %d bytes", part.name, existing, size)
            _hash_file(part, transfer.hasher, self.chunk_size)
        if existing < size:
            self._transfer(url, transfer, progress)

        done = part.stat().st_size
        if done < size:
            raise DownloadError(f"incomplete download of {file_name}: {done} of {size} bytes; .part kept for resume")
        if done > size:
            part.unlink()
            raise DownloadError(f"size mismatch for {file_name}: got {done}, expected {size} bytes; .part removed")
        digest = transfer.hasher.hexdigest()
        if digest != sha256.lower():
            part.unlink()
            raise DownloadError(f"SHA-256 mismatch for {file_name}: expected {sha256}, got {digest}; .part removed")
        os.replace(part, target)
        if progress:
            progress(transfer.progress)
        return target

    def _transfer(self, url: str, transfer: _Transfer, progress: ProgressCallback | None) -> None:
        state = transfer.progress
        headers = {"Range": f"bytes={state.bytes_done}-"} if state.bytes_done else {}
        last_report = time.monotonic()
        try:
            with self._client.stream("GET", url, headers=headers) as response:
                if response.status_code == 206:
                    mode = "ab"
                elif response.status_code == 200:
                    mode = "wb"
                    if state.bytes_done:
                        log.info("%s: server ignored the range request; restarting from zero", transfer.part.name)
                        transfer.hasher = hashlib.sha256()
                        state.bytes_done = state.resumed_from = 0
                else:
                    raise DownloadError(f"HTTP {response.status_code} for {url}")
                with transfer.part.open(mode) as fh:
                    for chunk in response.iter_bytes(self.chunk_size):
                        fh.write(chunk)
                        transfer.hasher.update(chunk)
                        state.bytes_done += len(chunk)
                        if state.bytes_done > state.bytes_total:  # mirrors are not allowlisted; cap what they send
                            raise _OversizedError
                        now = time.monotonic()
                        if progress and now - last_report >= self.progress_interval_s:
                            progress(state)
                            last_report = now
        except _OversizedError:
            transfer.part.unlink(missing_ok=True)
            raise DownloadError(
                f"{transfer.part.name}: the server sent more than the expected {state.bytes_total} bytes; .part removed"
            ) from None
        except httpx.HTTPError as exc:
            raise DownloadError(f"transfer of {transfer.part.name} failed: {exc}; .part kept for resume") from exc
