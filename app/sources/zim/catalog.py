"""Kiwix OPDS catalog (v2) and metalink parsing: the only module that talks to the Kiwix library.

Verified against the live catalog on 2026-09-17: ``library.kiwix.org`` redirects to
``opds.library.kiwix.org``; the ``name`` filter is exact (``klexikon_de_all``), the ``flavour``
filter is ignored by the server and applied here; the acquisition link points to a ``.meta4``
metalink whose ``length`` is only approximate. Size and SHA-256 come from the metalink itself.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

import httpx
from pydantic import BaseModel, Field

from app import __version__
from app.sources.zim.archive import archive_id, dump_date

log = logging.getLogger(__name__)

OPDS_DEFAULT_URL = "https://opds.library.kiwix.org/catalog/v2/entries"
USER_AGENT = f"compendious-text-fastapi/{__version__} (+https://wirlernenonline.de)"
ATOM = "{http://www.w3.org/2005/Atom}"
METALINK = "{urn:ietf:params:xml:ns:metalink}"
ACQUISITION_TYPE = "application/x-zim"
MAX_PAGES = 50
# A metalink is a few kB; an acquisition link that points at the archive itself must not be read into memory
MAX_METALINK_BYTES = 1 << 20


class CatalogEntry(BaseModel):
    """One archive offered by the catalog (one flavour of one name)."""

    name: str
    flavour: str = ""
    title: str = ""
    summary: str = ""
    language: str = ""
    updated: str = Field("", description="Dump date YYYY-MM-DD from <updated>")
    file_name: str
    metalink_url: str
    size: int = Field(0, description="Approximate size from the catalog; the metalink has the exact one")
    article_count: int = 0
    media_count: int = 0
    tags: list[str] = Field(default_factory=list)

    @property
    def archive_id(self) -> str:
        return archive_id(self.file_name)

    @property
    def download_url(self) -> str:
        return self.metalink_url.removesuffix(".meta4")

    @property
    def dump_date(self) -> str:
        return dump_date(self.file_name)

    @property
    def has_fulltext(self) -> bool:
        return "_ftindex:yes" in self.tags


class FeedPage(BaseModel):
    entries: list[CatalogEntry]
    total_results: int = 0
    start_index: int = 0
    items_per_page: int = 0


class Metalink(BaseModel):
    file_name: str
    size: int
    sha256: str
    urls: list[str] = Field(default_factory=list, description="Mirror URLs, best priority first")
    source_url: str = Field("", description="Where it was read, after redirects; empty is never trusted")


def _parse_xml(data: bytes) -> Element:
    # Feed and metalink come from the configured Kiwix host, carry no external entities, and expat
    # (>= 2.4) caps entity expansion; defusedxml would not earn its place as a dependency here.
    try:
        return ET.fromstring(data)  # noqa: S314
    except ET.ParseError as exc:  # a SyntaxError, not a ValueError: callers catch ValueError for bad input
        raise ValueError(f"not an XML document: {exc}") from exc


def _text(element: Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _int(element: Element, tag: str) -> int:
    value = _text(element, tag)
    return int(value) if value.isdigit() else 0


def _parse_entry(entry: Element) -> CatalogEntry | None:
    link = next((el for el in entry.findall(f"{ATOM}link") if el.get("type") == ACQUISITION_TYPE), None)
    href = link.get("href", "") if link is not None else ""
    file_name = href.rsplit("/", 1)[-1].removesuffix(".meta4")
    if not file_name.endswith(".zim"):
        return None
    length = link.get("length", "") if link is not None else ""
    return CatalogEntry(
        name=_text(entry, f"{ATOM}name"),
        flavour=_text(entry, f"{ATOM}flavour"),
        title=_text(entry, f"{ATOM}title"),
        summary=_text(entry, f"{ATOM}summary"),
        language=_text(entry, f"{ATOM}language"),
        updated=_text(entry, f"{ATOM}updated")[:10],
        file_name=file_name,
        metalink_url=href,
        size=int(length) if length.isdigit() else 0,
        article_count=_int(entry, f"{ATOM}articleCount"),
        media_count=_int(entry, f"{ATOM}mediaCount"),
        tags=[t for t in _text(entry, f"{ATOM}tags").split(";") if t],
    )


def parse_feed(xml: bytes) -> FeedPage:
    """Parse one page of the OPDS entries feed; entries without a ZIM link are skipped."""
    root = _parse_xml(xml)
    entries = [e for e in (_parse_entry(el) for el in root.findall(f"{ATOM}entry")) if e is not None]
    return FeedPage(
        entries=entries,
        total_results=_int(root, f"{ATOM}totalResults"),
        start_index=_int(root, f"{ATOM}startIndex"),
        items_per_page=_int(root, f"{ATOM}itemsPerPage"),
    )


def parse_metalink(xml: bytes) -> Metalink:
    """Parse a Metalink 4 document; raises ``ValueError`` when the SHA-256 hash is missing."""
    root = _parse_xml(xml)
    file_el = root.find(f"{METALINK}file")
    if file_el is None:
        raise ValueError("metalink without <file> element")
    sha256 = next((h.text for h in file_el.findall(f"{METALINK}hash") if h.get("type") == "sha-256"), None)
    if not sha256:
        raise ValueError(f"metalink for {file_el.get('name')!r} carries no sha-256 hash")
    mirrors = sorted(
        ((int(u.get("priority", "999")), (u.text or "").strip()) for u in file_el.findall(f"{METALINK}url")),
        key=lambda item: item[0],
    )
    return Metalink(
        file_name=file_el.get("name", ""),
        size=_int(file_el, f"{METALINK}size"),
        sha256=sha256.strip().lower(),
        urls=[url for _, url in mirrors if url],
    )


class KiwixCatalog:
    """Read access to the Kiwix library; used by the sync job and the admin catalog endpoint only."""

    def __init__(self, base_url: str = OPDS_DEFAULT_URL, client: httpx.Client | None = None, timeout: float = 30.0):
        self.base_url = base_url
        self._client = client or httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )

    def close(self) -> None:
        self._client.close()

    def entries(self, *, name: str | None = None, lang: str = "deu", count: int = 100) -> list[CatalogEntry]:
        """All entries matching the filters, following the feed's paging."""
        collected: list[CatalogEntry] = []
        start = 0
        for _ in range(MAX_PAGES):
            params = {"lang": lang, "count": str(count), "start": str(start)}
            if name:
                params["name"] = name
            response = self._client.get(self.base_url, params=params)
            response.raise_for_status()
            page = parse_feed(response.content)
            collected.extend(page.entries)
            start += len(page.entries)
            if not page.entries or start >= page.total_results:
                break
        return collected

    def latest(self, name: str, flavour: str) -> CatalogEntry | None:
        """Newest dump of one name and flavour, or ``None`` when the catalog has none."""
        matches = [e for e in self.entries(name=name) if e.name == name and e.flavour == flavour]
        if not matches:
            return None
        return max(matches, key=lambda e: (e.dump_date, e.updated))

    def metalink(self, url: str) -> Metalink:
        """The metalink at ``url``; ``source_url`` names where it was read after redirects, so the caller can
        check that host too. More than ``MAX_METALINK_BYTES`` raises ``ValueError``."""
        body = bytearray()
        with self._client.stream("GET", url) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_METALINK_BYTES:
                    raise ValueError(f"metalink at {url} is larger than {MAX_METALINK_BYTES} bytes")
            source_url = str(response.url)
        return parse_metalink(bytes(body)).model_copy(update={"source_url": source_url})
