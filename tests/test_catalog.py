"""Kiwix OPDS catalog client and metalink parser, offline against recorded responses."""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.sources.zim.catalog import KiwixCatalog, parse_feed, parse_metalink

OPDS = Path(__file__).parent / "fixtures" / "opds"
FEED_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/">
  <id>test</id><title>t</title><updated>2026-09-17T09:03:41Z</updated>
  <totalResults>{total}</totalResults><startIndex>{start}</startIndex><itemsPerPage>{per_page}</itemsPerPage>
  {entries}
</feed>"""
ENTRY_TEMPLATE = """<entry>
  <id>urn:uuid:{name}-{flavour}</id><title>{name}</title><updated>{date}T00:00:00Z</updated>
  <summary>s</summary><language>deu</language><name>{name}</name><flavour>{flavour}</flavour>
  <category></category><tags>_ftindex:yes</tags><articleCount>10</articleCount><mediaCount>0</mediaCount>
  <dc:issued>{date}T00:00:00Z</dc:issued>
  <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim"
        href="https://lb.download.kiwix.org/zim/other/{name}_{flavour}_{month}.zim.meta4" length="1024" />
</entry>"""
Handler = Callable[[httpx.Request], httpx.Response]


def _entry(name: str, flavour: str, month: str) -> str:
    return ENTRY_TEMPLATE.format(name=name, flavour=flavour, month=month, date=f"{month}-01")


def _feed(entries: list[str], total: int, start: int) -> bytes:
    return FEED_TEMPLATE.format(total=total, start=start, per_page=len(entries), entries="".join(entries)).encode()


def _catalog(handler: Handler) -> KiwixCatalog:
    return KiwixCatalog(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parse_feed_entries() -> None:
    page = parse_feed((OPDS / "klexikon_de_all.xml").read_bytes())
    assert page.total_results == 2
    maxi = next(e for e in page.entries if e.flavour == "maxi")
    assert maxi.name == "klexikon_de_all"
    assert maxi.archive_id == "klexikon_de_all_maxi"
    assert maxi.file_name == "klexikon_de_all_maxi_2026-08.zim"
    assert maxi.dump_date == "2026-08"
    assert maxi.download_url == "https://lb.download.kiwix.org/zim/other/klexikon_de_all_maxi_2026-08.zim"
    assert maxi.metalink_url == maxi.download_url + ".meta4"
    assert maxi.size == 135009280
    assert maxi.article_count == 5664
    assert maxi.has_fulltext
    assert maxi.title == "Klexikon – das Kinderlexikon"
    assert maxi.updated == "2026-08-07"


def test_parse_feed_page_meta() -> None:
    page = parse_feed((OPDS / "page_count2.xml").read_bytes())
    assert (page.total_results, page.start_index, page.items_per_page) == (306, 0, 2)
    assert len(page.entries) == 2
    assert page.entries[0].name == "freecodecamp_de_all"
    assert page.entries[0].archive_id == "freecodecamp_de_all"


def test_parse_metalink() -> None:
    metalink = parse_metalink((OPDS / "klexikon_de_all_maxi_2026-08.zim.meta4").read_bytes())
    assert metalink.file_name == "klexikon_de_all_maxi_2026-08.zim"
    assert metalink.size == 135008418  # the length attribute in the catalog (135009280) is only approximate
    assert metalink.sha256 == "763ddf84ad13e9f1d6ad4e364f048e7f18ecc2289c1d228d9dd4bb24e69d81b4"
    assert metalink.urls[0] == "https://ftp.fau.de/kiwix/zim/other/klexikon_de_all_maxi_2026-08.zim"
    assert len(metalink.urls) == 6


def test_latest_filters_flavour_client_side() -> None:
    wikipedia = (OPDS / "wikipedia_de_all.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["lang"] == "deu"
        if request.url.params.get("name") == "wikipedia_de_all":
            return httpx.Response(200, content=wikipedia)
        return httpx.Response(200, content=_feed([], 0, 0))

    catalog = _catalog(handler)
    entry = catalog.latest("wikipedia_de_all", "nopic")
    assert entry is not None
    assert entry.file_name == "wikipedia_de_all_nopic_2026-01.zim"
    assert entry.size == 14578860032
    assert catalog.latest("wikipedia_de_all", "hugepics") is None
    assert catalog.latest("nothing_de_all", "nopic") is None


def test_latest_picks_newest_dump() -> None:
    entries = [_entry("x_de_all", "nopic", "2026-01"), _entry("x_de_all", "nopic", "2026-07")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_feed(entries, 2, 0))

    entry = _catalog(handler).latest("x_de_all", "nopic")
    assert entry is not None
    assert entry.dump_date == "2026-07"


def test_entries_paginates() -> None:
    all_entries = [_entry(f"p{i}_de_all", "nopic", "2026-01") for i in range(5)]
    seen_starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("start", 0))
        count = int(request.url.params["count"])
        seen_starts.append(start)
        return httpx.Response(200, content=_feed(all_entries[start : start + count], len(all_entries), start))

    entries = _catalog(handler).entries(count=2)
    assert [e.name for e in entries] == [f"p{i}_de_all" for i in range(5)]
    assert seen_starts == [0, 2, 4]


def test_metalink_fetch_uses_client() -> None:
    body = (OPDS / "klexikon_de_all_maxi_2026-08.zim.meta4").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(".zim.meta4")
        return httpx.Response(200, content=body)

    url = "https://lb.download.kiwix.org/zim/other/klexikon_de_all_maxi_2026-08.zim.meta4"
    assert _catalog(handler).metalink(url).sha256.startswith("763ddf84")


KIWIX_METALINK = "https://lb.download.kiwix.org/zim/other/klexikon_de_all_maxi_2026-08.zim.meta4"


def test_a_metalink_reports_where_it_was_read_after_redirects() -> None:
    body = (OPDS / "klexikon_de_all_maxi_2026-08.zim.meta4").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "lb.download.kiwix.org":
            return httpx.Response(302, headers={"Location": "https://evil.example/x.zim.meta4"})
        return httpx.Response(200, content=body)

    catalog = KiwixCatalog(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    # The hash is the only integrity check of the archive: the sync checks this address against its allowlist
    assert catalog.metalink(KIWIX_METALINK).source_url == "https://evil.example/x.zim.meta4"


def test_a_link_to_the_archive_itself_is_not_read_into_memory() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024))  # an acquisition link without .meta4

    with pytest.raises(ValueError, match="larger than"):
        _catalog(handler).metalink(KIWIX_METALINK)


def test_a_metalink_that_is_no_xml_is_a_value_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body>Bad Gateway")  # an error page of a proxy

    with pytest.raises(ValueError):  # the sync records ValueError per subscription; a ParseError aborted the run
        _catalog(handler).metalink(KIWIX_METALINK)
