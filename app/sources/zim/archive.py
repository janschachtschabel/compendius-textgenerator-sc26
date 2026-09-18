"""Wrapper around one Kiwix ZIM archive (libzim): metadata, lookup, suggestion, full-text search."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
        self._cache: dict[str, ParsedArticle] = {}

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

    def parse(self, article: ZimArticle) -> ParsedArticle:
        cached = self._cache.get(article.path)
        if cached is None:
            cached = parse_article(article.html, article.title)
            if len(self._cache) > 256:
                self._cache.clear()
            self._cache[article.path] = cached
        return cached

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
