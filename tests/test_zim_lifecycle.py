"""The life of the archives on the volume: what goes when, and what a run leaves alone (audit 2026-09-28, BE-12, KO-21,
KO-24 and PE-08).

A retired archive was deleted only by a run after its retention, and the loop ran next after ZIM_SYNC_INTERVAL
(30 days), downloading first: after an update the old Wikipedia stayed a month, and the next update put three
generations on the volume, about 41 GB, with no check of the free space. After a change of ZIM_PROFILE the archives of
the old profile stayed active for good. A downloaded archive libzim could not open stayed on disk and came again with
every run, and the newest local file decided the adoption whether it opened or not. Every run rewrote active.json, so
every API worker reopened every archive and lost its caches.
"""

from __future__ import annotations

import os
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.cli_zim import _run_once
from app.jobs.zim_sync import FREE_SPACE_MARGIN, SyncOptions, ZimSync
from app.sources.zim.active import ACTIVE_FILE, read_active
from app.sources.zim.subscriptions import Subscription, SubscriptionManifest
from tests.test_zim_sync import MANIFEST, T0, FakeCatalog, FakeDownloader

COMPACT = SyncOptions(profile="compact")
BOOTSTRAP = SyncOptions(profile="compact", download_missing=True)
KLEXIKON = "klexikon_de_sample"


@pytest.fixture
def sources(sample_zims: dict[str, Path]) -> dict[str, Path]:
    return {
        "wikipedia_de_sample_2026-01.zim": sample_zims["wikipedia"],
        "klexikon_de_sample_2026-01.zim": sample_zims["klexikon"],
        "klexikon_de_sample_2026-08.zim": sample_zims["klexikon"],
        "klexikon_de_sample_2026-09.zim": sample_zims["klexikon"],
    }


def _install(directory: Path, sources: dict[str, Path], file_name: str) -> Path:
    return Path(shutil.copy(sources[file_name], directory / file_name))


class WatchingDownloader(FakeDownloader):
    """Notes which archives lay on the volume when each download began."""

    def __init__(self, sources: dict[str, Path]) -> None:
        super().__init__(sources)
        self.on_disk: list[list[str]] = []

    def download(self, url: str, target_dir: Path, **kwargs: Any) -> Path:
        self.on_disk.append(sorted(path.name for path in Path(target_dir).glob("*.zim")))
        return super().download(url, target_dir, **kwargs)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> Any:
        return self.now


def test_a_retired_archive_whose_time_is_up_goes_before_the_next_download(
    tmp_path: Path, sources: dict[str, Path]
) -> None:
    _install(tmp_path, sources, "klexikon_de_sample_2026-01.zim")
    clock, downloader = Clock(), WatchingDownloader(sources)
    catalog = FakeCatalog({KLEXIKON: "klexikon_de_sample_2026-08.zim"}, sources)
    sync = ZimSync(tmp_path, MANIFEST, catalog, downloader, clock=clock, retention=timedelta(hours=24))
    sync.run(COMPACT)  # 2026-08 replaces 2026-01, which retires

    catalog.offers[KLEXIKON] = "klexikon_de_sample_2026-09.zim"
    clock.now = T0 + timedelta(hours=25)
    report = sync.run(COMPACT)

    assert report.downloaded == [KLEXIKON]
    assert "klexikon_de_sample_2026-01.zim" not in downloader.on_disk[1]  # gone before the next download began
    assert report.pruned == ["klexikon_de_sample_2026-01.zim"]


def test_a_run_that_retires_an_archive_asks_the_loop_back_when_it_can_go(
    tmp_path: Path, sources: dict[str, Path]
) -> None:
    _install(tmp_path, sources, "klexikon_de_sample_2026-01.zim")
    catalog = FakeCatalog({KLEXIKON: "klexikon_de_sample_2026-08.zim"}, sources)
    sync = ZimSync(tmp_path, MANIFEST, catalog, FakeDownloader(sources), clock=Clock(), retention=timedelta(hours=24))

    wait = _run_once(sync, COMPACT, timedelta(days=30))

    assert wait == timedelta(hours=24)  # not the 30 days of ZIM_SYNC_INTERVAL
    empty = ZimSync(tmp_path / "leer", MANIFEST, None, FakeDownloader(sources), clock=Clock())
    assert _run_once(empty, COMPACT, timedelta(days=30))


def test_a_download_waits_until_the_volume_has_room_for_it(tmp_path: Path, sources: dict[str, Path]) -> None:
    _install(tmp_path, sources, "klexikon_de_sample_2026-01.zim")
    size = sources["klexikon_de_sample_2026-08.zim"].stat().st_size
    catalog = FakeCatalog({KLEXIKON: "klexikon_de_sample_2026-08.zim"}, sources)
    cramped = FakeDownloader(sources)

    report = ZimSync(
        tmp_path, MANIFEST, catalog, cramped, clock=Clock(), free_bytes=lambda path: size + FREE_SPACE_MARGIN - 1
    ).run(COMPACT)

    assert cramped.calls == [] and report.downloaded == []
    assert any("free" in error for error in report.errors) and not report.retry_soon
    roomy = FakeDownloader(sources)
    report = ZimSync(
        tmp_path, MANIFEST, catalog, roomy, clock=Clock(), free_bytes=lambda path: size + FREE_SPACE_MARGIN
    ).run(COMPACT)
    assert report.downloaded == [KLEXIKON]


# wikipedia in both profiles, klexikon only in standard
PROFILES = SubscriptionManifest(
    profiles={"compact": "", "standard": ""},
    subscriptions=[
        Subscription(
            id="wikipedia_de_sample",
            name="wikipedia_de_sample",
            project="wikipedia",
            required=True,
            profiles=["compact", "standard"],
        ),
        Subscription(id=KLEXIKON, name=KLEXIKON, project="klexikon", profiles=["standard"]),
    ],
)


def test_after_a_profile_change_the_archives_of_the_old_profile_retire(
    tmp_path: Path, sources: dict[str, Path]
) -> None:
    for name in ("wikipedia_de_sample_2026-01.zim", "klexikon_de_sample_2026-08.zim"):
        _install(tmp_path, sources, name)
    clock = Clock()
    sync = ZimSync(tmp_path, PROFILES, None, FakeDownloader(sources), clock=clock, retention=timedelta(hours=24))
    sync.run(SyncOptions(profile="standard"))

    sync.run(COMPACT)

    state = read_active(tmp_path)
    assert state is not None and list(state.archives) == ["wikipedia_de_sample"]
    assert [retired.file for retired in state.retired] == ["klexikon_de_sample_2026-08.zim"]
    clock.now = T0 + timedelta(hours=25)
    assert sync.run(COMPACT).pruned == ["klexikon_de_sample_2026-08.zim"]
    assert not (tmp_path / "klexikon_de_sample_2026-08.zim").exists()


def test_the_old_profile_serves_until_the_new_one_has_its_required_archives(
    tmp_path: Path, sources: dict[str, Path]
) -> None:
    switched = SubscriptionManifest(
        profiles={"compact": "", "standard": ""},
        subscriptions=[
            Subscription(
                id="wikipedia_de_sample",
                name="wikipedia_de_sample",
                project="wikipedia",
                required=True,
                profiles=["standard"],
            ),
            Subscription(id=KLEXIKON, name=KLEXIKON, project="klexikon", required=True, profiles=["compact"]),
        ],
    )
    _install(tmp_path, sources, "wikipedia_de_sample_2026-01.zim")
    sync = ZimSync(tmp_path, switched, None, FakeDownloader(sources), clock=Clock())
    sync.run(SyncOptions(profile="standard"))

    report = sync.run(COMPACT)  # klexikon is missing and cannot be fetched offline

    state = read_active(tmp_path)
    assert report.missing == [KLEXIKON]
    assert state is not None and list(state.archives) == ["wikipedia_de_sample"] and state.retired == []


def test_a_downloaded_archive_libzim_cannot_open_is_deleted_and_not_fetched_again(tmp_path: Path) -> None:
    unreadable = tmp_path / "quelle" / "wikipedia_de_sample_2026-01.zim"
    unreadable.parent.mkdir()
    unreadable.write_bytes(b"kein ZIM-Archiv" * 64)  # a dump in a ZIM version the pinned libzim cannot read
    offered = {"wikipedia_de_sample_2026-01.zim": unreadable}
    downloader = FakeDownloader(offered)
    sync = ZimSync(
        tmp_path / "zim", MANIFEST, FakeCatalog({"wikipedia_de_sample": unreadable.name}, offered), downloader
    )

    first = sync.run(BOOTSTRAP)
    second = sync.run(BOOTSTRAP)

    assert not (tmp_path / "zim" / unreadable.name).exists()  # 13.6 GB each, and a new one came with every dump
    state = read_active(tmp_path / "zim")
    assert state is not None and state.unreadable == [unreadable.name]
    assert len(downloader.calls) == 1  # the same dump is not fetched again, a newer one would be
    assert first.downloaded == second.downloaded == [] and any(unreadable.name in e for e in second.errors)


def test_the_newest_local_file_that_opens_is_adopted(tmp_path: Path, sources: dict[str, Path]) -> None:
    _install(tmp_path, sources, "klexikon_de_sample_2026-01.zim")
    (tmp_path / "klexikon_de_sample_2026-08.zim").write_bytes(b"kein ZIM-Archiv" * 64)

    report = ZimSync(tmp_path, MANIFEST, None, FakeDownloader(sources), clock=Clock()).run(COMPACT)

    state = read_active(tmp_path)
    assert state is not None and state.archives[KLEXIKON].file == "klexikon_de_sample_2026-01.zim"
    assert report.adopted == [KLEXIKON] and any("klexikon_de_sample_2026-08.zim" in e for e in report.errors)


def test_a_run_that_changes_nothing_leaves_active_json_alone(tmp_path: Path, sources: dict[str, Path]) -> None:
    for name in ("wikipedia_de_sample_2026-01.zim", "klexikon_de_sample_2026-08.zim"):
        _install(tmp_path, sources, name)
    sync = ZimSync(tmp_path, MANIFEST, None, FakeDownloader(sources), clock=Clock())
    sync.run(COMPACT)
    active = tmp_path / ACTIVE_FILE
    os.utime(active, ns=(1_000_000_000, 1_000_000_000))  # a rewrite would stamp it with the time of the run

    sync.run(COMPACT)

    assert active.stat().st_mtime_ns == 1_000_000_000  # the API workers keep their open archives and caches
