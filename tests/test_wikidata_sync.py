"""The Wikidata sync: a new installation gets the index, a newer Wikipedia archive a newer one (D64).

dumps.wikimedia.org is simulated with MockTransport: the list of runs of the German Wikipedia, each run's
dumpstatus.json with size and SHA-1 of its files, and the files themselves, written like the real dumps: page_props,
page and, for the English titles behind the DBpedia URIs (D65), langlinks.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.jobs.lock import LockHeldError
from app.settings import Settings
from app.sources.wikidata.index import WikidataIndex, build_index
from app.sources.wikidata.sync import (
    DUMP_DIR,
    LOCK_FILE,
    WikidataSync,
    WikidataSyncError,
    active_wikipedia_date,
    build_sync,
    find_run,
    read_status,
)
from app.sources.zim.active import ActiveArchive, ActiveState, write_active
from app.sources.zim.downloader import DownloadError
from tests.test_wikidata_index import PAGES, PROPS, write_dumps, write_langlinks

DUMPS = "https://dumps.wikimedia.org"
OTHER_ABBE = [(1, "wikibase_item", "Q999101"), *PROPS[1:]]  # a later run: Ernst Abbe's number differs


class FakeDumps:
    """The dump site: runs with their status and files; ``calls`` lists every path asked for."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.files: dict[str, bytes] = {}
        self.status: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []

    def add(
        self,
        run: str,
        completed: str,
        *,
        page_done: bool = True,
        langlinks_done: bool = True,
        props: list[tuple[int, str, str]] = PROPS,
        wrong_sha1: bool = False,
    ) -> None:
        page_props, page = write_dumps(self.directory / run, pages=PAGES, props=props, completed=completed)
        langlinks = write_langlinks(self.directory / run, completed=completed)
        jobs = {}
        for job, table, path, done in (
            ("pagepropstable", "page_props", page_props, True),
            ("pagetable", "page", page, page_done),
            ("langlinkstable", "langlinks", langlinks, langlinks_done),
        ):
            name = f"dewiki-{run}-{table}.sql.gz"
            body = path.read_bytes()
            self.files[f"/dewiki/{run}/{name}"] = body
            sha1 = "0" * 40 if wrong_sha1 else hashlib.sha1(body).hexdigest()  # noqa: S324 - as Wikimedia publishes
            files = {name: {"size": len(body), "url": f"/dewiki/{run}/{name}", "sha1": sha1, "md5": "-"}}
            jobs[job] = {"status": "done" if done else "in-progress", "updated": completed, "files": files}
        self.status[run] = {"jobs": jobs, "version": "0.8"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if path == "/dewiki/":
            links = "".join(f'<a href="{run}/">{run}/</a>\n' for run in sorted(self.status))
            return httpx.Response(200, text=f'<html><body><a href="../">../</a>\n{links}<a href="latest/">latest/</a>')
        if match := re.fullmatch(r"/dewiki/(\d{8})/dumpstatus\.json", path):
            return httpx.Response(200, json=self.status[match.group(1)])
        if path in self.files:
            return httpx.Response(200, stream=httpx.ByteStream(self.files[path]))  # streamed, as the network does
        return httpx.Response(404)

    def downloads(self) -> list[str]:
        return [path for path in self.calls if path.endswith(".sql.gz")]


@pytest.fixture
def site(tmp_path: Path) -> FakeDumps:
    return FakeDumps(tmp_path / "site")


def _sync(state: Path, site: FakeDumps, archive: date | None = None) -> WikidataSync:
    client = httpx.Client(transport=httpx.MockTransport(site.handler))
    return WikidataSync(state / "wikidata.db", client=client, base_url=DUMPS, archive_date=lambda: archive)


def test_the_newest_run_whose_two_tables_are_done_is_taken(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260801", "2026-08-04 18:13:34")
    site.add("20260901", "2026-09-04 18:02:11", page_done=False)  # page is still being written
    run = find_run(httpx.Client(transport=httpx.MockTransport(site.handler)), DUMPS)
    assert run.date == date(2026, 8, 1)
    assert run.page_props.name == "dewiki-20260801-page_props.sql.gz"
    assert run.page.url == f"{DUMPS}/dewiki/20260801/dewiki-20260801-page.sql.gz"
    assert run.page.size == len(site.files["/dewiki/20260801/dewiki-20260801-page.sql.gz"])


def test_a_run_whose_langlinks_are_not_done_is_passed_over(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260801", "2026-08-04 18:13:34")
    site.add("20260901", "2026-09-04 18:02:11", langlinks_done=False)
    run = find_run(httpx.Client(transport=httpx.MockTransport(site.handler)), DUMPS)
    assert run.id == "20260801" and run.langlinks.name == "dewiki-20260801-langlinks.sql.gz"


def test_without_a_finished_run_the_sync_says_so(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260901", "2026-09-04 18:02:11", page_done=False)
    with pytest.raises(WikidataSyncError, match="no run"):
        find_run(httpx.Client(transport=httpx.MockTransport(site.handler)), DUMPS)


def test_a_new_installation_gets_the_index_and_keeps_no_dump(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260901", "2026-09-07 16:21:03")
    sync = _sync(tmp_path / "state", site)
    reason = sync.due()
    assert reason == "no index"
    meta = sync.run(reason)
    assert meta["dump"] == "2026-09-07" and meta["articles"] > 0
    index = WikidataIndex(tmp_path / "state" / "wikidata.db")
    assert index.qid("Ernst Abbe") == "Q999001" and index.english("Römisches Reich") == "Roman Empire"
    assert list((tmp_path / "state" / DUMP_DIR).glob("*")) == []  # 750 MB of dumps do not stay behind
    status = read_status(tmp_path / "state")
    assert status is not None and status["last_run"]["ok"] is True
    assert status["last_run"]["run"] == "20260901" and status["last_run"]["reason"] == "no index"


def test_an_index_that_covers_the_archive_stays_and_nothing_is_asked(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260901", "2026-09-07 16:21:03")
    _sync(tmp_path / "state", site).run()
    site.calls.clear()
    assert _sync(tmp_path / "state", site, archive=date(2026, 1, 15)).due() is None
    assert site.calls == []


def test_a_newer_wikipedia_archive_brings_the_newer_run(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260801", "2026-08-04 18:13:34")
    _sync(tmp_path / "state", site).run()
    site.add("20260901", "2026-09-07 16:21:03", props=OTHER_ABBE)
    sync = _sync(tmp_path / "state", site, archive=date(2026, 9, 15))
    assert sync.due() == "archive newer than the index"
    assert sync.run()["dump"] == "2026-09-07"
    assert WikidataIndex(tmp_path / "state" / "wikidata.db").qid("Ernst Abbe") == "Q999101"


def test_a_newer_archive_without_a_newer_run_waits_instead_of_fetching_the_same_run(
    tmp_path: Path, site: FakeDumps
) -> None:
    site.add("20260901", "2026-09-07 16:21:03")
    _sync(tmp_path / "state", site).run()
    site.calls.clear()
    # The archive is dated after the run: only a later run can cover its new articles, a rebuild would not
    assert _sync(tmp_path / "state", site, archive=date(2026, 9, 20)).due() is None
    assert site.downloads() == []


def test_an_unusable_index_is_rebuilt(tmp_path: Path, site: FakeDumps) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "wikidata.db").write_bytes(b"no index")
    assert _sync(tmp_path / "state", site).due() == "index unusable"


def test_forced_rebuilds_a_current_index(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260901", "2026-09-07 16:21:03")
    _sync(tmp_path / "state", site).run()
    assert _sync(tmp_path / "state", site).due(force=True) == "forced"


def test_a_dump_with_the_wrong_checksum_keeps_the_index_there_is(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260801", "2026-08-04 18:13:34")
    _sync(tmp_path / "state", site).run()
    site.add("20260901", "2026-09-07 16:21:03", props=OTHER_ABBE, wrong_sha1=True)
    with pytest.raises(DownloadError, match="SHA-1 mismatch"):
        _sync(tmp_path / "state", site, archive=date(2026, 9, 15)).run()
    assert not (tmp_path / "state" / LOCK_FILE).exists()
    index = WikidataIndex(tmp_path / "state" / "wikidata.db")
    assert index.meta()["dump"] == "2026-08-04" and index.qid("Ernst Abbe") == "Q999001"
    status = read_status(tmp_path / "state")
    assert status is not None and status["last_run"]["ok"] is False
    assert "SHA-1 mismatch" in status["last_run"]["error"]


def test_a_second_run_does_not_start_while_one_holds_the_lock(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260901", "2026-09-07 16:21:03")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / LOCK_FILE).write_text("pid 1\n", encoding="utf-8")
    with pytest.raises(LockHeldError):
        _sync(tmp_path / "state", site).run()
    assert site.downloads() == []


def test_the_archive_date_comes_from_active_json(tmp_path: Path) -> None:
    archives = {
        "wikipedia_de_all_nopic": ActiveArchive(
            id="wikipedia_de_all_nopic",
            file="wikipedia_de_all_nopic_2026-01.zim",
            date="2026-01-15",
            project="wikipedia",
        ),
        "klexikon_de_all_maxi": ActiveArchive(
            id="klexikon_de_all_maxi", file="klexikon_de_all_maxi_2026-08.zim", date="2026-08-07", project="klexikon"
        ),
    }
    write_active(tmp_path, ActiveState(archives=archives))
    assert active_wikipedia_date(tmp_path) == date(2026, 1, 15)


def test_with_zim_paths_the_archive_date_is_the_month_of_the_file_name(tmp_path: Path) -> None:
    paths = [Path("zim/wikipedia_de_all_nopic_2026-01.zim"), Path("zim/klexikon_de_all_maxi_2026-08.zim")]
    assert active_wikipedia_date(tmp_path, paths) == date(2026, 1, 1)


def test_without_a_wikipedia_archive_there_is_no_archive_date(tmp_path: Path) -> None:
    assert active_wikipedia_date(tmp_path) is None
    assert active_wikipedia_date(tmp_path, [Path("klexikon_de_all_maxi_2026-08.zim")]) is None


def test_the_status_file_is_json_an_operator_can_read(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260901", "2026-09-07 16:21:03")
    _sync(tmp_path / "state", site).run()
    raw = json.loads((tmp_path / "state" / "wikidata_status.json").read_text(encoding="utf-8"))
    assert raw["last_run"]["articles"] > 0 and raw["last_run"]["dump"] == "2026-09-07"


def test_the_dump_site_is_asked_over_https_only(tmp_path: Path, site: FakeDumps) -> None:
    # The run list and dumpstatus.json carry the checksums; read over plain http they could be forged on the way
    site.add("20260901", "2026-09-07 16:21:03")
    with pytest.raises(DownloadError, match="https"):
        find_run(httpx.Client(transport=httpx.MockTransport(site.handler)), "http://dumps.wikimedia.org")
    assert site.calls == []


def test_a_redirect_of_the_dump_status_to_another_host_is_not_followed(tmp_path: Path, site: FakeDumps) -> None:
    # dumpstatus.json holds the checksums the downloads are held to; it must come from the host asked, nowhere else
    site.add("20260901", "2026-09-07 16:21:03")
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.path.endswith("dumpstatus.json"):
            return httpx.Response(302, headers={"Location": "https://elsewhere.example/dumpstatus.json"})
        return site.handler(request)

    with pytest.raises(httpx.HTTPStatusError):
        find_run(httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True), DUMPS)
    assert "elsewhere.example" not in hosts


def test_an_interrupted_run_says_so_releases_the_lock_and_counts_as_no_failure(
    tmp_path: Path, site: FakeDumps, monkeypatch: pytest.MonkeyPatch
) -> None:
    site.add("20260901", "2026-09-07 16:21:03")

    def stopped(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt  # what stop_on_sigterm raises when the container stops

    monkeypatch.setattr("app.sources.wikidata.sync.build_index", stopped)
    with pytest.raises(KeyboardInterrupt):
        _sync(tmp_path / "state", site).run("no index")
    status = read_status(tmp_path / "state")
    assert status is not None and status["state"] == "idle"
    assert status["last_run"]["ok"] is None and status["last_run"]["error"] == "KeyboardInterrupt"
    assert not (tmp_path / "state" / LOCK_FILE).exists()


def test_what_an_older_run_left_behind_is_removed(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260901", "2026-09-07 16:21:03")
    dumps = tmp_path / "state" / DUMP_DIR
    dumps.mkdir(parents=True)
    (dumps / "dewiki-20260801-page.sql.gz.part").write_bytes(b"x" * 100)  # a run cut short a month ago
    _sync(tmp_path / "state", site).run()
    assert list(dumps.iterdir()) == []


def test_a_check_that_cannot_reach_the_dump_site_is_recorded(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260801", "2026-08-04 18:13:34")
    _sync(tmp_path / "state", site).run()

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    sync = WikidataSync(
        tmp_path / "state" / "wikidata.db",
        client=httpx.Client(transport=httpx.MockTransport(down)),
        base_url=DUMPS,
        archive_date=lambda: date(2026, 9, 15),
    )
    with pytest.raises(httpx.HTTPStatusError):
        sync.due()
    status = read_status(tmp_path / "state")
    assert status is not None and status["last_run"]["ok"] is False  # the gauge and its alert see it
    assert status["last_run"]["error"].startswith("check:")


def test_the_sync_of_an_installation_reads_its_settings(tmp_path: Path) -> None:
    wikipedia = ActiveArchive(
        id="wikipedia_de_all_nopic", file="wikipedia_de_all_nopic_2026-10.zim", date="2026-10-15", project="wikipedia"
    )
    write_active(tmp_path / "zim", ActiveState(archives={"wikipedia_de_all_nopic": wikipedia}))
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        state_dir=tmp_path / "state",
        zim_dir=tmp_path / "zim",
        zim_paths="",
        wikidata_dumps_url="https://mirror.example/dumps",
    )
    sync = build_sync(settings)
    assert sync.index_path == settings.wikidata_db_path
    assert sync.base_url == "https://mirror.example/dumps" and sync.archive_date() == date(2026, 10, 15)


def test_a_good_check_after_a_failed_one_clears_the_failure(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260901", "2026-09-07 16:21:03")
    _sync(tmp_path / "state", site).run("no index")
    down = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    late = WikidataSync(
        tmp_path / "state" / "wikidata.db", client=down, base_url=DUMPS, archive_date=lambda: date(2026, 9, 20)
    )
    with pytest.raises(httpx.HTTPStatusError):
        late.due()
    # The site answers again and has nothing newer than the index's run: the failure is over
    assert _sync(tmp_path / "state", site, archive=date(2026, 9, 20)).due() is None
    status = read_status(tmp_path / "state")
    assert status is not None and status["last_run"]["ok"] is True and status["last_run"]["error"] is None
    assert status["last_run"]["reason"] == "check" and status["last_run"]["run"] == "20260901"


def test_an_index_built_by_hand_after_a_failed_check_clears_the_failure(tmp_path: Path, site: FakeDumps) -> None:
    site.add("20260801", "2026-08-04 18:13:34")
    _sync(tmp_path / "state", site).run()
    down = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    sync = WikidataSync(
        tmp_path / "state" / "wikidata.db", client=down, base_url=DUMPS, archive_date=lambda: date(2026, 9, 15)
    )
    with pytest.raises(httpx.HTTPStatusError):
        sync.due()
    page_props, page = write_dumps(tmp_path / "hand", completed="2026-09-17 16:21:03")
    langlinks = write_langlinks(tmp_path / "hand", completed="2026-09-17 16:25:40")
    build_index(page_props, page, tmp_path / "state" / "wikidata.db", langlinks=langlinks)
    # The index covers the archive now: nothing is asked of the site, and the failed check no longer counts
    assert sync.due() is None
    status = read_status(tmp_path / "state")
    assert status is not None and status["last_run"]["ok"] is True and status["last_run"]["run"] is None
