"""Registry of active archives: topic resolution and corpus construction (PLAN.md 4.1, 4.2)."""

from __future__ import annotations

import logging
import re
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

from app.domain.models import Resolution, Source
from app.knowledge.related import is_blacklisted, rank_related_candidates
from app.knowledge.topic import topic_stem
from app.sources.zim.active import read_active
from app.sources.zim.archive import ZimArchive, ZimArticle
from app.sources.zim.html import ParsedArticle
from app.templates.schema import TemplateSlot

log = logging.getLogger(__name__)

SEARCH_RESERVE = 3  # corpus slots kept for slot-targeted full-text hits
RELATED_MIN_CHARS = 350


def listed_meanings(article: ParsedArticle) -> list[str]:
    """The links a disambiguation page offers as meanings - the ones that stand in its list.

    Such a page opens with a sentence of its own, and the links in it are etymology, not meanings. They
    stand in front of everything else, so with no context to score against they won: measured against the
    real Wikipedia on 2026-09-21, the topic "Punkt" resolved to "Latein" and "Wende" to "Althochdeutsch",
    and both were reported as alternative meanings as well.

    Deciding this by searching the list *text* was measured and thrown out: it dropped 19 real meanings to
    remove 3 etymology links, because the rendered label of a link is not its title - "Punktierung (Musik)"
    reads as "Punktierung", "Bezirk Friedrichshain-Kreuzberg" as "Friedrichshain-Kreuzberg". Where a link
    stands is not a guess, so the parser records it.

    A page whose meanings are prose rather than a list keeps all its links: narrowing to nothing would lose
    the topic altogether.
    """
    return list(article.list_links) or list(article.links)


def context_score(context_words: Collection[str], title: str, text: str) -> int:
    """How many of the caller's context words a candidate of a disambiguation page shows.

    The title counts as much as the opening text, because that is where a German disambiguation page keeps
    the distinction - "Rolle (Physik)", "Feld (Numismatik)" - while the body often never repeats it.
    Measured against the real Wikipedia on 2026-09-21: the article behind "Rolle (Physik)" opens with "Eine
    Rolle ist ein Maschinenelement" and does not contain the word Physik at all, so it scored zero and the
    first link of the page won instead. Reading the title as well decided that case and left the other
    seventeen checked topics exactly where they were.

    ``context_words`` are expected in lower case; the candidate is not.
    """
    haystack = f"{title} {text[:1500]}".lower()
    return sum(1 for word in context_words if word in haystack)


class ZimRegistry:
    """Holds the open archives (leading source first) and answers topic questions."""

    def __init__(self, paths: Sequence[Path]) -> None:
        self.archives: list[ZimArchive] = []
        self.reload(paths)

    def reload(self, paths: Sequence[Path]) -> None:
        """Open the given archives and swap them in as one list; unreadable files are logged and skipped."""
        archives: list[ZimArchive] = []
        for path in paths:
            try:
                archives.append(ZimArchive(Path(path)))
            except Exception as exc:  # a broken archive must not take the service down
                log.error("cannot open ZIM archive %s: %s", path, exc)
        self.archives = sorted(archives, key=lambda a: (a.priority, a.file_name))

    def only(self, archive_ids: Sequence[str]) -> ZimRegistry:
        """A view on the named archives, in the order of this registry; the archives stay open and shared."""
        wanted = set(archive_ids)
        view = ZimRegistry([])
        view.archives = [archive for archive in self.archives if archive.id in wanted]
        return view

    @classmethod
    def discover(cls, directory: Path) -> ZimRegistry:
        paths = sorted(p for p in Path(directory).glob("*.zim")) if Path(directory).exists() else []
        return cls(paths)

    @classmethod
    def from_active(cls, zim_dir: Path) -> ZimRegistry:
        """Registry from ``active.json``; without that file every ``*.zim`` in the directory is used.

        A corrupt state file is logged and yields an empty registry, so ``/ready`` shows the problem
        instead of the process crash-looping until the sync job rewrites the file.
        """
        try:
            state = read_active(zim_dir)
        except ValueError as exc:
            log.error("%s", exc)
            return cls([])
        if state is None:
            return cls.discover(zim_dir)
        return cls(state.paths(zim_dir))

    @property
    def ready(self) -> bool:
        return bool(self.archives)

    def has_ids(self, required: Sequence[str]) -> list[str]:
        present = {a.id for a in self.archives}
        return [r for r in required if r not in present]

    def snapshot(self) -> list[dict[str, Any]]:
        return [a.snapshot() for a in self.archives]

    @property
    def primary_archive(self) -> ZimArchive | None:
        return self.archives[0] if self.archives else None

    # -- topic resolution ------------------------------------------------------------------------
    def resolve_topic(self, topic: str, context: Sequence[str] = (), query: str | None = None) -> Resolution:
        resolution = Resolution(query=query or topic, normalized=topic, context=list(context))
        for archive in self.archives:
            article = archive.read(topic)
            if article is None:
                continue
            parsed = archive.parse(article)
            if parsed.is_disambiguation:
                resolution.disambiguation = True
                meanings = listed_meanings(parsed)  # one list: what is offered is what is chosen from
                resolution.alternatives = meanings[:8]
                chosen = self._pick_from_disambiguation(archive, meanings, context)
                if chosen is not None:
                    resolution.title, resolution.path, resolution.project = chosen.title, chosen.path, archive.project
                    return resolution
                continue
            resolution.title, resolution.path, resolution.project = article.title, article.path, archive.project
            return resolution

        lead = self.primary_archive
        if lead is None:
            return resolution
        suggestions = [t for t in lead.suggest(topic, 10) if "(begriffsklärung)" not in t.lower()]
        if suggestions:
            exact = [t for t in suggestions if t.lower() == topic.lower()]
            best = exact[0] if exact else suggestions[0]
            resolution.alternatives = [t for t in suggestions if t != best][:8]
            found = lead.read(best)
            if found is not None and not lead.parse(found).is_disambiguation:
                resolution.title, resolution.path, resolution.project = found.title, found.path, lead.project
                return resolution
        hits = lead.search(topic, 5)
        if hits:
            resolution.alternatives = hits[1:9]
            found = lead.read(hits[0])
            if found is not None and not lead.parse(found).is_disambiguation:
                resolution.title, resolution.path, resolution.project = found.title, found.path, lead.project
        return resolution

    def _pick_from_disambiguation(
        self, archive: ZimArchive, links: Sequence[str], context: Sequence[str]
    ) -> ZimArticle | None:
        context_words = {w.lower() for c in context for w in re.findall(r"\w{4,}", c)}
        candidates: list[tuple[int, int, ZimArticle]] = []
        for title in links[:12]:
            article = archive.read(title)
            if article is None:
                continue
            parsed = archive.parse(article)
            if parsed.is_disambiguation:
                continue
            score = context_score(context_words, parsed.title, parsed.text)
            candidates.append((score, len(candidates), article))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][2]

    # -- corpus ------------------------------------------------------------------------------------
    def build_corpus(self, resolution: Resolution, slots: Sequence[TemplateSlot], max_articles: int) -> list[Source]:
        if resolution.title is None or resolution.project is None:
            return []
        primary_archive = next((a for a in self.archives if a.project == resolution.project), None)
        if primary_archive is None:
            return []
        article = primary_archive.read(resolution.path or resolution.title)
        if article is None:
            return []
        primary = primary_archive.to_source(article, is_primary=True)
        primary.origin = "primary"
        sources: list[Source] = [primary]
        seen = {(primary.project, primary.title.lower())}

        # Same topic in the other archives (e.g. Klexikon in simple language).
        for archive in self.archives:
            if archive is primary_archive:
                continue
            for candidate in [primary.title, *primary.aliases[:2]]:
                found = archive.read(candidate)
                if found is None or archive.parse(found).is_disambiguation:
                    continue
                key = (archive.project, found.title.lower())
                if key in seen:
                    break
                seen.add(key)
                twin = archive.to_source(found, is_primary=False)
                twin.origin = "same_topic"
                sources.append(twin)
                break

        # Related sub-articles via ranked internal links of the primary article.
        budget_related = max(0, max_articles - len(sources) - SEARCH_RESERVE)
        for title in rank_related_candidates(primary, primary.links):
            if budget_related <= 0:
                break
            related = self._read_source(primary_archive, title, seen)
            if related is None:
                continue
            if _text_length(related) >= RELATED_MIN_CHARS:
                related.origin = "linked"
                sources.append(related)
                budget_related -= 1

        # Slot-targeted full-text hits fill blocks the main article rarely covers.
        if primary_archive.has_fulltext:
            stem = topic_stem(primary.title)
            for slot in slots:
                if len(sources) >= max_articles:
                    break
                if not slot.search_queries:
                    continue
                query = f"{primary.title} {' '.join(slot.search_queries[:3])}"
                for title in primary_archive.search(query, 4):
                    if len(sources) >= max_articles:
                        break
                    if is_blacklisted(title):
                        continue
                    hit = self._read_source(primary_archive, title, seen)
                    if hit is None:
                        continue
                    haystack = f"{hit.title} {hit.lead_text}".lower()
                    if stem and stem in haystack:
                        hit.origin = "search"
                        sources.append(hit)
        return sources

    def _read_source(self, archive: ZimArchive, title: str, seen: set[tuple[str, str]]) -> Source | None:
        key = (archive.project, title.lower())
        if key in seen:
            return None
        article = archive.read(title)
        if article is None:
            return None
        key = (archive.project, article.title.lower())
        if key in seen:
            return None
        parsed = archive.parse(article)
        if parsed.is_disambiguation:
            return None
        seen.add(key)
        return archive.to_source(article, is_primary=False)

    def lookup(self, title: str) -> Source | None:
        """Read a single article from the first archive that has it (used for actors and glossary)."""
        for archive in self.archives:
            article = archive.read(title)
            if article is None:
                continue
            if archive.parse(article).is_disambiguation:
                return None
            found = archive.to_source(article, is_primary=False)
            found.origin = "lookup"
            return found
        return None


def _text_length(source: Source) -> int:
    return sum(len(p.text) for s in source.sections for p in s.paragraphs)
