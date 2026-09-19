"""Sync job: adopt local files, bootstrap, update with retirement and pruning; no network."""

import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest

from app.jobs.zim_sync import STATUS_FILE, SyncOptions, ZimSync, read_status
from app.sources.zim.active import read_active
from app.sources.zim.catalog import CatalogEntry, Metalink
from app.sources.zim.downloader import DownloadError
from app.sources.zim.subscriptions import Subscription, SubscriptionManifest

T0 = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)
MANIFEST = SubscriptionManifest(
    profiles={"compact": "", "standard": ""},
    subscriptions=[
        Subscription(
            id="wikipedia_de_sample",
            name="wikipedia_de_sample",
            project="wikipedia",
            required=True,
            profiles=["compact", "standard"],
        ),
        Subscription(
            id="klexikon_de_sample",
            name="klexikon_de_sample",
            project="klexikon",
            required=True,
            profiles=["compact", "standard"],
        ),
    ],
)
BASE = "https://lb.download.kiwix.org/zim/test/"
COMPACT = SyncOptions(profile="compact", download_missing=False)
BOOTSTRAP = SyncOptions(profile="compact", download_missing=True)


class FakeCatalog:
    """Offers one dump per name; ``sources`` maps offered file names to sample archives."""

    def __init__(self, offers: dict[str, str], sources: dict[str, Path], fail: bool = False) -> None:
        self.offers, self.sources, self.fail = offers, sources, fail

    def latest(self, name: str, flavour: str) -> CatalogEntry | None:
        if self.fail:
            raise httpx.ConnectError("catalog unreachable")
        file_name = self.offers.get(name)
        if file_name is None:
            return None
        return CatalogEntry(
            name=name, flavour=flavour, file_name=file_name, metalink_url=f"{BASE}{file_name}.meta4", size=1
        )

    def metalink(self, url: str) -> Metalink:
        file_name = url.rsplit("/", 1)[-1].removesuffix(".meta4")
        source = self.sources[file_name]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return Metalink(
            file_name=file_name, size=source.stat().st_size, sha256=digest, urls=[url.removesuffix(".meta4")]
        )


class FakeDownloader:
    def __init__(self, sources: dict[str, Path], fail: bool = False) -> None:
        self.sources, self.fail = sources, fail
        self.calls: list[str] = []

    def download(self, url: str, target_dir: Path, *, sha256: str, size: int, progress: Any = None) -> Path:
        self.calls.append(url)
        if self.fail:
            raise DownloadError("network down")
        file_name = url.rsplit("/", 1)[-1]
        assert hashlib.sha256(self.sources[file_name].read_bytes()).hexdigest() == sha256
        return Path(shutil.copy(self.sources[file_name], Path(target_dir) / file_name))


@pytest.fixture
def sources(sample_zims: dict[str, Path]) -> dict[str, Path]:
    return {
        "wikipedia_de_sample_2026-01.zim": sample_zims["wikipedia"],
        "klexikon_de_sample_2026-01.zim": sample_zims["klexikon"],
        "klexikon_de_sample_2026-08.zim": sample_zims["klexikon"],
    }


def _install(tmp_path: Path, sources: dict[str, Path], file_name: str) -> Path:
    return Path(shutil.copy(sources[file_name], tmp_path / file_name))


def _sync(tmp_path: Path, catalog: Any, downloader: Any, clock: Any = lambda: T0, **kwargs: Any) -> ZimSync:
    return ZimSync(tmp_path, MANIFEST, catalog, downloader, clock=clock, **kwargs)


def test_bootstrap_downloads_missing_required_archives(tmp_path: Path, sources: dict[str, Path]) -> None:
    offers = {
        "wikipedia_de_sample": "wikipedia_de_sample_2026-01.zim",
        "klexikon_de_sample": "klexikon_de_sample_2026-08.zim",
    }
    downloader = FakeDownloader(sources)
    report = _sync(tmp_path, FakeCatalog(offers, sources), downloader).run(BOOTSTRAP)
    assert sorted(report.downloaded) == ["klexikon_de_sample", "wikipedia_de_sample"]
    assert report.errors == []
    state = read_active(tmp_path)
    assert state is not None
    assert state.profile == "compact"
    assert state.archives["klexikon_de_sample"].file == "klexikon_de_sample_2026-08.zim"
    assert state.archives["klexikon_de_sample"].date == "2026-08-07"
    assert state.archives["klexikon_de_sample"].uuid
    assert state.archives["klexikon_de_sample"].size > 0
    status = read_status(tmp_path)
    assert status is not None
    assert status["state"] == "idle"
    assert status["last_run"]["downloaded"] == report.downloaded
    assert (tmp_path / STATUS_FILE).exists()


def test_missing_archives_are_only_reported_without_bootstrap(tmp_path: Path, sources: dict[str, Path]) -> None:
    offers = {
        "wikipedia_de_sample": "wikipedia_de_sample_2026-01.zim",
        "klexikon_de_sample": "klexikon_de_sample_2026-08.zim",
    }
    downloader = FakeDownloader(sources)
    report = _sync(tmp_path, FakeCatalog(offers, sources), downloader).run(COMPACT)
    assert sorted(report.missing) == ["klexikon_de_sample", "wikipedia_de_sample"]
    assert downloader.calls == []
    state = read_active(tmp_path)
    assert state is not None
    assert state.archives == {}


def test_adopts_local_files_offline(tmp_path: Path, sources: dict[str, Path]) -> None:
    _install(tmp_path, sources, "klexikon_de_sample_2026-08.zim")
    (tmp_path / "klexikon_de_sample_2026-09.zim.part").write_bytes(b"partial")  # never adopted
    report = _sync(tmp_path, None, FakeDownloader(sources)).run(COMPACT)
    assert report.adopted == ["klexikon_de_sample"]
    assert report.missing == ["wikipedia_de_sample"]
    state = read_active(tmp_path)
    assert state is not None
    assert state.archives["klexikon_de_sample"].file == "klexikon_de_sample_2026-08.zim"
    assert state.archives["klexikon_de_sample"].project == "klexikon"


def test_update_retires_old_file_and_prunes_after_retention(tmp_path: Path, sources: dict[str, Path]) -> None:
    _install(tmp_path, sources, "klexikon_de_sample_2026-01.zim")
    catalog = FakeCatalog({"klexikon_de_sample": "klexikon_de_sample_2026-08.zim"}, sources)
    now = T0
    sync = _sync(tmp_path, catalog, FakeDownloader(sources), clock=lambda: now, retention=timedelta(hours=24))

    report = sync.run(COMPACT)
    assert report.adopted == ["klexikon_de_sample"]
    assert report.downloaded == ["klexikon_de_sample"]
    state = read_active(tmp_path)
    assert state is not None
    assert state.archives["klexikon_de_sample"].file == "klexikon_de_sample_2026-08.zim"
    assert [r.file for r in state.retired] == ["klexikon_de_sample_2026-01.zim"]
    assert (tmp_path / "klexikon_de_sample_2026-01.zim").exists()

    now = T0 + timedelta(hours=23)
    assert sync.run(COMPACT).pruned == []
    now = T0 + timedelta(hours=25)
    report = sync.run(COMPACT)
    assert report.pruned == ["klexikon_de_sample_2026-01.zim"]
    assert report.skipped == ["klexikon_de_sample"]
    assert not (tmp_path / "klexikon_de_sample_2026-01.zim").exists()
    state = read_active(tmp_path)
    assert state is not None
    assert state.retired == []


def test_download_failure_keeps_previous_state(tmp_path: Path, sources: dict[str, Path]) -> None:
    _install(tmp_path, sources, "klexikon_de_sample_2026-01.zim")
    catalog = FakeCatalog({"klexikon_de_sample": "klexikon_de_sample_2026-08.zim"}, sources)
    report = _sync(tmp_path, catalog, FakeDownloader(sources, fail=True)).run(BOOTSTRAP)
    assert any("klexikon_de_sample" in e and "network down" in e for e in report.errors)
    state = read_active(tmp_path)
    assert state is not None
    assert state.archives["klexikon_de_sample"].file == "klexikon_de_sample_2026-01.zim"
    assert state.retired == []


def test_catalog_failure_is_reported_not_raised(tmp_path: Path, sources: dict[str, Path]) -> None:
    report = _sync(tmp_path, FakeCatalog({}, sources, fail=True), FakeDownloader(sources)).run(BOOTSTRAP)
    assert len(report.errors) == 2
    assert "catalog unreachable" in report.errors[0]
    status = read_status(tmp_path)
    assert status is not None
    assert status["state"] == "idle"


def test_metalink_from_a_foreign_host_is_not_fetched(tmp_path: Path, sources: dict[str, Path]) -> None:
    class ForeignCatalog(FakeCatalog):
        fetched: ClassVar[list[str]] = []

        def latest(self, name: str, flavour: str) -> CatalogEntry | None:
            entry = super().latest(name, flavour)
            if entry is None:
                return None
            return entry.model_copy(update={"metalink_url": f"https://evil.example/{entry.file_name}.meta4"})

        def metalink(self, url: str) -> Metalink:
            self.fetched.append(url)
            return super().metalink(url)

    offers = {"wikipedia_de_sample": "wikipedia_de_sample_2026-01.zim"}
    report = _sync(tmp_path, ForeignCatalog(offers, sources), FakeDownloader(sources)).run(BOOTSTRAP)
    assert ForeignCatalog.fetched == []
    assert report.downloaded == [] and any("evil.example" in error for error in report.errors)


def test_partial_downloads_of_superseded_dumps_are_removed(tmp_path: Path, sources: dict[str, Path]) -> None:
    _install(tmp_path, sources, "klexikon_de_sample_2026-08.zim")
    stale = tmp_path / "klexikon_de_sample_2026-01.zim.part"  # an older dump that never finished
    pending = tmp_path / "klexikon_de_sample_2026-09.zim.part"  # a newer dump the next run resumes
    foreign = tmp_path / "freecodecamp_de_all_2026-01.zim.part"  # no subscription of this profile: not ours to judge
    for part in (stale, pending, foreign):
        part.write_bytes(b"x" * 16)
    report = _sync(tmp_path, None, FakeDownloader(sources)).run(COMPACT)
    assert not stale.exists() and pending.exists() and foreign.exists()
    assert report.pruned == [stale.name]


def test_an_aborted_run_leaves_a_final_status(
    tmp_path: Path, sources: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def volume_full(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("app.jobs.zim_sync.write_active", volume_full)
    offers = {"wikipedia_de_sample": "wikipedia_de_sample_2026-01.zim"}
    later = iter([T0, T0 + timedelta(minutes=5)] + [T0 + timedelta(minutes=9)] * 20)
    sync = _sync(tmp_path, FakeCatalog(offers, sources), FakeDownloader(sources), clock=lambda: next(later))
    with pytest.raises(OSError, match="No space left"):
        sync.run(BOOTSTRAP)
    status = read_status(tmp_path)
    assert status is not None
    # Not "running" without an end: the timestamp and the error count reach the alerts
    assert status["state"] == "error"
    assert status["last_run"]["finished_at"] == (T0 + timedelta(minutes=9)).isoformat()
    assert any("Lauf abgebrochen" in error and "OSError" in error for error in status["last_run"]["errors"])
