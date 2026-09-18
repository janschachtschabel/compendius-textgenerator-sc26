"""Downloader: range resume, hash verification, host allowlist; server simulated with MockTransport."""

import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.sources.zim.downloader import Downloader, DownloadError, DownloadProgress, validate_file_name

BLOB = bytes(range(256)) * 40  # 10240 bytes
SHA = hashlib.sha256(BLOB).hexdigest()
URL = "https://lb.download.kiwix.org/zim/other/test_de_all_maxi_2026-08.zim"
FILE = "test_de_all_maxi_2026-08.zim"
Handler = Callable[[httpx.Request], httpx.Response]


def _server(blob: bytes, calls: list[httpx.Request], *, honor_range: bool = True, status: int = 200) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if status != 200:
            return httpx.Response(status)
        range_header = request.headers.get("Range")
        if range_header and honor_range:
            start = int(range_header.removeprefix("bytes=").split("-")[0])
            body = blob[start:]
            headers = {"Content-Range": f"bytes {start}-{len(blob) - 1}/{len(blob)}", "Content-Length": str(len(body))}
            return httpx.Response(206, content=body, headers=headers)
        return httpx.Response(200, content=blob, headers={"Content-Length": str(len(blob))})

    return handler


def _downloader(handler: Handler) -> Downloader:
    return Downloader(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_fresh_download_verifies_hash_and_reports_progress(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    progress: list[DownloadProgress] = []
    path = _downloader(_server(BLOB, calls)).download(
        URL, tmp_path, sha256=SHA, size=len(BLOB), progress=progress.append
    )
    assert path == tmp_path / FILE
    assert path.read_bytes() == BLOB
    assert not (tmp_path / f"{FILE}.part").exists()
    assert "Range" not in calls[0].headers
    assert progress[-1].bytes_done == len(BLOB)
    assert progress[-1].bytes_total == len(BLOB)
    assert progress[-1].percent == 100.0


def test_resume_continues_partial_file(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    (tmp_path / f"{FILE}.part").write_bytes(BLOB[:4000])
    progress: list[DownloadProgress] = []
    path = _downloader(_server(BLOB, calls)).download(
        URL, tmp_path, sha256=SHA, size=len(BLOB), progress=progress.append
    )
    assert calls[0].headers["Range"] == "bytes=4000-"
    assert path.read_bytes() == BLOB
    assert progress[-1].resumed_from == 4000


def test_server_ignoring_range_restarts_from_zero(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    (tmp_path / f"{FILE}.part").write_bytes(b"garbage")
    path = _downloader(_server(BLOB, calls, honor_range=False)).download(URL, tmp_path, sha256=SHA, size=len(BLOB))
    assert path.read_bytes() == BLOB


def test_complete_part_is_verified_without_transfer(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    (tmp_path / f"{FILE}.part").write_bytes(BLOB)
    path = _downloader(_server(BLOB, calls)).download(URL, tmp_path, sha256=SHA, size=len(BLOB))
    assert calls == []
    assert path.read_bytes() == BLOB


def test_hash_mismatch_removes_part_and_raises(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="SHA-256"):
        _downloader(_server(BLOB, [])).download(URL, tmp_path, sha256="00" * 32, size=len(BLOB))
    assert list(tmp_path.iterdir()) == []


def test_short_download_keeps_part_for_resume(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="incomplete"):
        _downloader(_server(BLOB, [])).download(URL, tmp_path, sha256=SHA, size=len(BLOB) + 1)
    assert (tmp_path / f"{FILE}.part").stat().st_size == len(BLOB)


def test_oversized_part_is_discarded(tmp_path: Path) -> None:
    (tmp_path / f"{FILE}.part").write_bytes(BLOB + b"x")
    path = _downloader(_server(BLOB, [])).download(URL, tmp_path, sha256=SHA, size=len(BLOB))
    assert path.read_bytes() == BLOB


def test_disallowed_host_is_rejected_before_any_request(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    with pytest.raises(DownloadError, match="host"):
        _downloader(_server(BLOB, calls)).download(
            "https://evil.example/zim/x_de_all_2026-01.zim", tmp_path, sha256=SHA, size=1
        )
    assert calls == []


def test_http_error_is_reported(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="404"):
        _downloader(_server(BLOB, [], status=404)).download(URL, tmp_path, sha256=SHA, size=len(BLOB))


def test_transport_errors_keep_part_and_raise(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(DownloadError, match="boom"):
        _downloader(handler).download(URL, tmp_path, sha256=SHA, size=len(BLOB))


def test_file_name_validation() -> None:
    assert validate_file_name("wikipedia_de_all_nopic_2026-01.zim") == "wikipedia_de_all_nopic_2026-01.zim"
    for bad in ("../x.zim", "x.zim.part", "a b.zim", "x/y.zim", "", "x.txt", ".hidden.zim"):
        with pytest.raises(ValueError):
            validate_file_name(bad)


def test_plain_http_is_rejected_before_any_request(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    with pytest.raises(DownloadError, match="https"):
        _downloader(_server(BLOB, calls)).download(URL.replace("https://", "http://"), tmp_path, sha256=SHA, size=1)
    assert calls == []


def test_a_stream_longer_than_announced_is_aborted(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    announced = len(BLOB) // 4
    with pytest.raises(DownloadError, match="more than the expected"):
        _downloader(_server(BLOB, calls)).download(URL, tmp_path, sha256=SHA, size=announced)
    assert list(tmp_path.glob("*")) == []  # nothing is kept from a source that ignores the announced size
