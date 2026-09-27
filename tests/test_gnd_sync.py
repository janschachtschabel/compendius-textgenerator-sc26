"""The GND sync: a new installation gets the GND index, a newer release of the DNB's dumps a newer one (D65).

data.dnb.de is simulated with MockTransport: the checksum file (SHA-256 per dated file name, as the DNB publishes it),
the size of each file on HEAD, and the files themselves, written like the DNB's Turtle dumps.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.settings import Settings
from app.sources.gnd.index import GndIndex
from app.sources.gnd.sync import (
    DUMP_DIR,
    LOCK_FILE,
    GndSync,
    GndSyncError,
    build_gnd_sync,
    find_release,
    read_status,
)
from app.sources.zim.downloader import DownloadError
from tests.test_gnd_index import PLACES, SUBJECTS, write_gnd

DNB = "https://data.dnb.de/opendata"


class FakeDnb:
    """The DNB's opendata folder: dumps per version, the checksum file over all of them; ``calls`` lists requests."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.files: dict[str, bytes] = {}
        self.sums: list[str] = []
        self.calls: list[tuple[str, str]] = []

    def add(
        self, version: str, *, kinds: tuple[str, ...] = ("sachbegriff", "geografikum"), wrong: bool = False
    ) -> None:
        for kind in kinds:
            name = f"authorities-gnd-{kind}_lds_{version}.ttl.gz"
            body = write_gnd(self.directory / name, SUBJECTS if kind == "sachbegriff" else PLACES).read_bytes()
            self.files[name] = body
            digest = "0" * 64 if wrong else hashlib.sha256(body).hexdigest()
            self.sums.append(f"{digest} {name}")
            other = name.replace(".ttl.gz", ".jsonld.gz")  # the other formats stand in the same file
            self.sums.append(f"{hashlib.sha256(other.encode()).hexdigest()} {other}")

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        self.calls.append((request.method, name))
        if name == "001_Pruefsumme_Checksum.txt":
            return httpx.Response(200, text="\n".join(self.sums) + "\n")
        if name in self.files:
            body = self.files[name]
            if request.method == "HEAD":
                return httpx.Response(200, headers={"Content-Length": str(len(body))})
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    def downloads(self) -> list[str]:
        return [name for method, name in self.calls if method == "GET" and name.endswith(".ttl.gz")]


@pytest.fixture
def dnb(tmp_path: Path) -> FakeDnb:
    return FakeDnb(tmp_path / "dnb")


def _client(dnb: FakeDnb) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(dnb.handler))


def _sync(state: Path, dnb: FakeDnb) -> GndSync:
    return GndSync(state / "gnd.db", client=_client(dnb), base_url=DNB)


def test_the_newest_release_with_both_dumps_is_taken(dnb: FakeDnb) -> None:
    dnb.add("20250901")
    dnb.add("20260217", kinds=("sachbegriff",))  # the places of this release are not out yet
    release = find_release(_client(dnb), DNB)
    assert release.id == "20250901" and release.date == date(2025, 9, 1)
    assert [dump.name for dump in release.files] == [
        "authorities-gnd-sachbegriff_lds_20250901.ttl.gz",
        "authorities-gnd-geografikum_lds_20250901.ttl.gz",
    ]
    assert release.files[0].size == len(dnb.files["authorities-gnd-sachbegriff_lds_20250901.ttl.gz"])


def test_without_a_complete_release_the_sync_says_so(dnb: FakeDnb) -> None:
    dnb.add("20260217", kinds=("geografikum",))
    with pytest.raises(GndSyncError, match="no GND release"):
        find_release(_client(dnb), DNB)


def test_a_new_installation_gets_the_gnd_index_and_keeps_no_dump(tmp_path: Path, dnb: FakeDnb) -> None:
    dnb.add("20260217")
    sync = _sync(tmp_path / "state", dnb)
    reason = sync.due()
    assert reason == "no index"
    meta = sync.run(reason)
    assert meta["release"] == "2026-02-17" and meta["records"] == 8
    hit = GndIndex(tmp_path / "state" / "gnd.db").find("Zahl", qid=None)
    assert hit is not None and hit.number == "4067271-2"
    assert list((tmp_path / "state" / DUMP_DIR).glob("*")) == []
    status = read_status(tmp_path / "state")
    assert status is not None and status["last_run"]["ok"] is True and status["last_run"]["run"] == "20260217"


def test_an_index_of_the_newest_release_stays(tmp_path: Path, dnb: FakeDnb) -> None:
    dnb.add("20260217")
    _sync(tmp_path / "state", dnb).run()
    dnb.calls.clear()
    assert _sync(tmp_path / "state", dnb).due() is None
    assert dnb.downloads() == []


def test_a_newer_release_brings_a_new_index(tmp_path: Path, dnb: FakeDnb) -> None:
    dnb.add("20250901")
    _sync(tmp_path / "state", dnb).run()
    dnb.add("20260217")
    sync = _sync(tmp_path / "state", dnb)
    assert sync.due() == "newer release"
    assert sync.run("newer release")["release"] == "2026-02-17"


def test_a_dump_with_the_wrong_checksum_keeps_the_index_there_is(tmp_path: Path, dnb: FakeDnb) -> None:
    dnb.add("20250901")
    _sync(tmp_path / "state", dnb).run()
    dnb.add("20260217", wrong=True)
    with pytest.raises(DownloadError, match="SHA-256 mismatch"):
        _sync(tmp_path / "state", dnb).run()
    assert GndIndex(tmp_path / "state" / "gnd.db").meta()["release"] == "2025-09-01"
    status = read_status(tmp_path / "state")
    assert status is not None and status["last_run"]["ok"] is False
    assert not (tmp_path / "state" / LOCK_FILE).exists()


def test_the_dnb_is_asked_over_https_only(dnb: FakeDnb) -> None:
    dnb.add("20260217")
    with pytest.raises(DownloadError, match="https"):
        find_release(_client(dnb), "http://data.dnb.de/opendata")
    assert dnb.calls == []


def test_a_redirect_of_the_checksum_file_is_not_followed(dnb: FakeDnb) -> None:
    dnb.add("20260217")
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.path.endswith("001_Pruefsumme_Checksum.txt"):
            return httpx.Response(302, headers={"Location": "https://elsewhere.example/sums.txt"})
        return dnb.handler(request)

    with pytest.raises(httpx.HTTPStatusError):
        find_release(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True), DNB)
    assert "elsewhere.example" not in hosts


def test_a_check_that_cannot_reach_the_dnb_is_recorded(tmp_path: Path, dnb: FakeDnb) -> None:
    dnb.add("20260217")
    _sync(tmp_path / "state", dnb).run()
    down = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        GndSync(tmp_path / "state" / "gnd.db", client=down, base_url=DNB).due()
    status = read_status(tmp_path / "state")
    assert status is not None and status["last_run"]["ok"] is False
    assert status["last_run"]["error"].startswith("check:")


def test_an_unusable_index_is_rebuilt(tmp_path: Path, dnb: FakeDnb) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "gnd.db").write_bytes(b"kein SQLite")
    assert _sync(tmp_path / "state", dnb).due() == "index unusable"


def test_the_sync_of_an_installation_reads_its_settings(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        state_dir=tmp_path / "state",
        gnd_dumps_url="https://mirror.example/gnd",
    )
    sync = build_gnd_sync(settings)
    assert sync.index_path == settings.gnd_db_path and sync.base_url == "https://mirror.example/gnd"
