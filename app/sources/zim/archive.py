"""Wrapper around one Kiwix ZIM archive (libzim): metadata, lookup, suggestion, full-text search."""

from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import libzim
from libzim.search import Query, Searcher
from libzim.suggestion import SuggestionSearcher

from app.domain.models import Source, SourceRole
from app.sources.zim.html import ParsedArticle, parse_article

log = logging.getLogger(__name__)

PROJECT_ROLES: dict[str, SourceRole] = {
    "wikipedia": SourceRole.LEITQUELLE,
    "klexikon": SourceRole.EINFACHE_SPRACHE,
    "wikibooks": SourceRole.LEHRBUCH,
    "wikiversity": SourceRole.HOCHSCHULE,
}
PARSE_CACHE_SIZE = 256  # parsed articles kept per archive; a corpus reads about 12 plus lookups
MAX_REDIRECTS = 3  # a chain longer than this is broken, not followed
# A redirect to a section of another article is a page of its own in these archives: a meta refresh to
# "./Bruchrechnung#Nenner", with the title as its only text (M35)
SECTION_REDIRECT = re.compile(
    r"""<meta\s+http-equiv=["']refresh["']\s+content=["']\d+;\s*url=['"]?\./([^'"#]+)""", re.IGNORECASE
)
REDIRECT_HEAD = 2_000  # the meta refresh stands in the head; an article's body is never searched for it
LINK_CACHE_SIZE = 20_000  # link names resolved per archive; a corpus asks about 160 to 2,200 (M25)
PROJECT_PRIORITY = {"wikipedia": 0, "klexikon": 1, "wikiversity": 2, "wikibooks": 3}
PROJECT_AUTHORITY = {"wikipedia": 0.95, "klexikon": 0.85, "wikibooks": 0.80, "wikiversity": 0.75}
PROJECT_URLS = {
    "wikipedia": "https://de.wikipedia.org/wiki/",
    "klexikon": "https://klexikon.zum.de/wiki/",
    "wikibooks": "https://de.wikibooks.org/wiki/",
    "wikiversity": "https://de.wikiversity.org/wiki/",
}


def classify_project(file_name: str, creator: str = "", title: str = "") -> str:
    haystack = f"{file_name} {creator} {title}".lower()
    for project in (
        "klexikon",
        "wikibooks",
        "wikiversity",
        "wikiquote",
        "wikisource",
        "wiktionary",
        "wikivoyage",
        "wikipedia",
    ):
        if project in haystack:
            return project
    return "other"


def archive_id(file_name: str) -> str:
    """Subscription id: file name without date and extension, e.g. wikipedia_de_all_nopic."""
    stem = file_name[:-4] if file_name.endswith(".zim") else file_name
    return re.sub(r"_\d{4}-\d{2}$", "", stem)


def dump_date(file_name: str) -> str:
    """``YYYY-MM`` from a Kiwix file name (``…_2026-08.zim``), empty when the name carries no date."""
    match = re.search(r"_(\d{4}-\d{2})\.zim$", file_name)
    return match.group(1) if match else ""


@dataclass
class ZimArticle:
    title: str
    path: str
    html: str


class ZimArchive:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._archive: Any = libzim.Archive(self.path)
        self.file_name = self.path.name
        self.id = archive_id(self.file_name)
        self.uuid = str(self._archive.uuid)
        self.title_meta = self._meta("Title")
        self.date = self._meta("Date")
        self.language = self._meta("Language") or "deu"
        self.flavour = self._meta("Flavour")
        self.project = classify_project(self.file_name, self._meta("Creator"), self.title_meta)
        self.role = PROJECT_ROLES.get(self.project, SourceRole.SONSTIGE)
        self.authority = PROJECT_AUTHORITY.get(self.project, 0.6)
        self.priority = PROJECT_PRIORITY.get(self.project, 9)
        self.has_fulltext = bool(self._archive.has_fulltext_index)
        self.article_count = int(self._archive.article_count)
        self._cache: OrderedDict[str, ParsedArticle] = OrderedDict()  # LRU of parsed articles
        self._cache_lock = threading.Lock()  # one archive serves all request threads
        self._titles: OrderedDict[str, str | None] = OrderedDict()  # LRU of resolved link names

    def _meta(self, key: str) -> str:
        try:
            value: bytes = self._archive.get_metadata(key)
            return value.decode("utf-8", "replace").strip()
        except Exception:  # metadata keys are optional
            return ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file": self.file_name,
            "project": self.project,
            "date": self.date,
            "uuid": self.uuid,
            "articles": self.article_count,
            "fulltext_index": self.has_fulltext,
        }

    # -- lookup --------------------------------------------------------------------------------
    def _entry(self, identifier: str) -> Any | None:
        variants = [identifier, identifier.replace("_", " "), identifier.replace(" ", "_")]
        if identifier:
            variants.append(identifier[0].upper() + identifier[1:])
        for candidate in dict.fromkeys(variants):
            for has, get in (
                (self._archive.has_entry_by_title, self._archive.get_entry_by_title),
                (self._archive.has_entry_by_path, self._archive.get_entry_by_path),
            ):
                try:
                    if has(candidate):
                        return get(candidate)
                except Exception as exc:  # libzim raises on odd input; try the next variant
                    log.debug("lookup of %r failed: %s", candidate, exc)
        return None

    def has(self, identifier: str) -> bool:
        """Whether an article of this name exists, without unpacking it: a title lookup, no content read."""
        return self._entry(identifier) is not None

    def canonical_title(self, identifier: str) -> str | None:
        """The title of the article a name leads to, redirects followed, without reading its content.

        Kept per archive: every corpus on a topic resolves the links of its main article, which took 1.9 s for
        Deutschland in a first corpus and 0.19 s in a second one on the same topic (M25). The cache holds strings
        only, so an archive nobody uses closes its file at once.
        """
        with self._cache_lock:
            if identifier in self._titles:
                self._titles.move_to_end(identifier)
                return self._titles[identifier]
        entry = self._entry(identifier)
        for _ in range(MAX_REDIRECTS):
            if entry is None or not entry.is_redirect:
                break
            entry = entry.get_redirect_entry()
        title = None if entry is None or entry.is_redirect else str(entry.title)
        with self._cache_lock:
            self._titles[identifier] = title
            while len(self._titles) > LINK_CACHE_SIZE:
                self._titles.popitem(last=False)
        return title

    def read(self, identifier: str) -> ZimArticle | None:
        entry = self._entry(identifier)
        if entry is None:
            return None
        if entry.is_redirect:
            entry = entry.get_redirect_entry()
        item = entry.get_item()
        if not str(item.mimetype).startswith("text/html"):
            return None
        html = bytes(item.content).decode("utf-8", "replace")
        return ZimArticle(title=str(entry.title), path=str(entry.path), html=html)

    def read_article(self, identifier: str) -> ZimArticle | None:
        """``read``, and a redirect to a section of another article followed to that article (M35).

        ``read`` keeps such a page as it is: Wikidata gives many of them an object of their own, and /entities names
        it (D43). A resolution needs the article: the page holds nothing but its title.
        """
        article = self.read(identifier)
        for _ in range(MAX_REDIRECTS):
            found = SECTION_REDIRECT.search(article.html, 0, REDIRECT_HEAD) if article is not None else None
            target = self.read(unquote(found.group(1))) if found is not None else None
            if target is None or article is None or target.path == article.path:
                break
            article = target
        return article

    def parse(self, article: ZimArticle) -> ParsedArticle:
        with self._cache_lock:
            cached = self._cache.get(article.path)
            if cached is not None:
                self._cache.move_to_end(article.path)
                return cached
        parsed = parse_article(article.html, article.title)  # outside the lock: parsing is the slow part
        with self._cache_lock:
            self._cache[article.path] = parsed
            self._cache.move_to_end(article.path)
            while len(self._cache) > PARSE_CACHE_SIZE:
                self._cache.popitem(last=False)
        return parsed

    def suggest(self, prefix: str, limit: int = 8) -> list[str]:
        try:
            searcher = SuggestionSearcher(self._archive)
            results = searcher.suggest(prefix)
            return [str(self._archive.get_entry_by_path(p).title) for p in results.getResults(0, limit)]
        except Exception as exc:
            log.debug("suggestion failed for %r: %s", prefix, exc)
            return []

    def search(self, query: str, limit: int = 10) -> list[str]:
        if not self.has_fulltext:
            return []
        try:
            searcher = Searcher(self._archive)
            results = searcher.search(Query().set_query(query))
            return [str(self._archive.get_entry_by_path(p).title) for p in results.getResults(0, limit)]
        except Exception as exc:
            log.debug("search failed for %r: %s", query, exc)
            return []

    # -- conversion ----------------------------------------------------------------------------
    def url_for(self, path: str) -> str:
        base = PROJECT_URLS.get(self.project)
        if base:
            return base + quote(path.replace(" ", "_"), safe="()_,-.:")
        return f"zim://{self.file_name}/{quote(path)}"

    def to_source(self, article: ZimArticle, *, is_primary: bool) -> Source:
        parsed = self.parse(article)
        slug = re.sub(r"[^\w()-]+", "_", article.path)
        authority = self.authority if is_primary else round(self.authority * 0.85, 2)
        return Source(
            source_id=f"{self.project}:{slug}",
            project=self.project,
            role=self.role,
            title=article.title,
            url=self.url_for(article.path),
            zim_file=self.file_name,
            zim_uuid=self.uuid,
            zim_date=self.date,
            entry_path=article.path,
            authority_score=authority,
            is_primary=is_primary,
            aliases=list(parsed.aliases),
            links=list(parsed.links),
            sections=[s.model_copy(deep=True) for s in parsed.sections],
        )
