"""The corpus of a topic: the main article, its twin, linked sub-articles, full-text hits, the articles the LLM named
and a material's own article (PLAN.md 4.2).

Moved out of ``ZimRegistry`` (audit 2026-09-27, AR-03): the registry holds the archives, the knowledge package builds
the corpus. ``build_corpus`` is the one entry.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.models import Resolution, Source
from app.knowledge.related import is_blacklisted, rank_related_candidates
from app.knowledge.topic import TopicMention
from app.sources.zim.archive import ZimArchive
from app.templates.schema import TemplateSlot

if TYPE_CHECKING:
    from app.sources.zim.registry import ZimRegistry

SEARCH_RESERVE = 3  # corpus slots kept for slot-targeted full-text hits
RELATED_MIN_CHARS = 350
NODE_ORIGIN = "node"  # the article of a material sent along with a topic (D47)
NAMED_ORIGIN = "named"  # an article the LLM named for the topic with its overview (D63)


def build_corpus(
    registry: ZimRegistry,
    resolution: Resolution,
    slots: Sequence[TemplateSlot],
    max_articles: int,
    material: str | None = None,
    named: Sequence[str] = (),
) -> list[Source]:
    """The sources of a topic over the archives of ``registry``; see ``_CorpusBuilder.build_corpus``."""
    return _CorpusBuilder(registry).build_corpus(resolution, slots, max_articles, material, named)


@dataclass
class _Draft:
    """The corpus while it is built: the main article, its archive, what the corpus holds and has read."""

    archive: ZimArchive
    primary: Source
    max_articles: int
    sources: list[Source]
    seen: set[tuple[str, str]]


class _CorpusBuilder:
    """The archives of a registry, as one corpus reads them: the leading one first."""

    def __init__(self, registry: ZimRegistry) -> None:
        self.archives: list[ZimArchive] = list(registry.archives)
        self.primary_archive: ZimArchive | None = registry.primary_archive

    def build_corpus(
        self,
        resolution: Resolution,
        slots: Sequence[TemplateSlot],
        max_articles: int,
        material: str | None = None,
        named: Sequence[str] = (),
    ) -> list[Source]:
        """The main article, its twin, linked sub-articles and full-text hits for the blocks, at most ``max_articles``.

        ``material`` is the own article of a material sent along with a topic (D47): it joins as a source of its own
        (origin ``node``) when it links with the main article, whatever ``max_articles`` says. ``named`` are the
        articles the LLM named for the topic (D63): they take the places of the linked sub-articles and the hits.
        Split in steps (audit 2026-09-27, WA-01: complexity 26).
        """
        draft = self._main(resolution, max_articles)
        if draft is None:
            return []
        self._add_twins(draft)
        linked_to = LinkedTo(draft.archive, draft.primary)
        if named:  # read where they were looked up, the leading archive; without a new one the corpus stays as before
            before = len(draft.sources)
            self._add_named(self.primary_archive or draft.archive, named, draft.sources, draft.seen, max_articles)
            if len(draft.sources) > before:
                if material and material != draft.primary.title:
                    self._add_material(draft.archive, material, draft.sources, linked_to)
                return draft.sources
        self._add_linked(draft)
        if draft.archive.has_fulltext:
            self._add_hits(draft, slots, linked_to)
        if material and material != draft.primary.title:
            self._add_material(draft.archive, material, draft.sources, linked_to)
        return draft.sources

    def _main(self, resolution: Resolution, max_articles: int) -> _Draft | None:
        """The corpus as it starts: the main article the resolution names, from its archive; ``None`` without it."""
        if resolution.title is None or resolution.project is None:
            return None
        archive = next((a for a in self.archives if a.project == resolution.project), None)
        if archive is None:
            return None
        article = archive.read(resolution.path or resolution.title)
        if article is None:
            return None
        primary = archive.to_source(article, is_primary=True)
        primary.origin = "primary"
        return _Draft(archive, primary, max_articles, [primary], {(primary.project, primary.title.lower())})

    def _add_twins(self, draft: _Draft) -> None:
        """Same topic in the other archives (e.g. Klexikon in simple language)."""
        primary = draft.primary
        for archive in self.archives:
            if archive is draft.archive:
                continue
            for candidate in [primary.title, *primary.aliases[:2]]:
                found = archive.read(candidate)
                if found is None or archive.parse(found).is_disambiguation:
                    continue
                key = (archive.project, found.title.lower())
                if key in draft.seen:
                    break
                draft.seen.add(key)
                twin = archive.to_source(found, is_primary=False)
                twin.origin = "same_topic"
                draft.sources.append(twin)
                break

    def _add_linked(self, draft: _Draft) -> None:
        """Related sub-articles via ranked internal links of the primary article."""
        budget_related = max(0, draft.max_articles - len(draft.sources) - SEARCH_RESERVE)
        for title in rank_related_candidates(draft.primary, draft.primary.links):
            if budget_related <= 0:
                break
            related = self._read_source(draft.archive, title, draft.seen)
            if related is None:
                continue
            if _text_length(related) >= RELATED_MIN_CHARS:
                related.origin = "linked"
                draft.sources.append(related)
                budget_related -= 1

    def _add_hits(self, draft: _Draft, slots: Sequence[TemplateSlot], linked_to: LinkedTo) -> None:
        """Slot-targeted full-text hits fill blocks the main article rarely covers."""
        topic = TopicMention.of(draft.primary.title)
        for slot in slots:
            if len(draft.sources) >= draft.max_articles:
                break
            if not slot.search_queries:
                continue
            query = f"{draft.primary.title} {' '.join(slot.search_queries[:3])}"
            for title in draft.archive.search(query, 4):
                if len(draft.sources) >= draft.max_articles:
                    break
                if is_blacklisted(title):
                    continue
                hit = self._read_source(draft.archive, title, draft.seen)
                if hit is not None and topic.found_in(f"{hit.title} {hit.lead_text}"):
                    hit.origin = "search"
                    draft.sources.append(hit)
        # M25: of the hits with no link to or from the main article most were unfit; without them the printed
        # unfit paragraphs of 20 topics fell from 25 to 12. Their places stay empty, as measured.
        draft.sources = [s for s in draft.sources if s.origin != "search" or linked_to(s)]

    def _add_named(
        self, archive: ZimArchive, titles: Sequence[str], sources: list[Source], seen: set[tuple[str, str]], cap: int
    ) -> None:
        """The articles the LLM named, in its order, until the corpus holds ``cap`` articles (D63).

        Unlike linked sub-articles and hits they need no length, no mention of the topic in their paragraphs and no
        hit check: the model named them for the topic, and so they were measured (M37).
        """
        for title in titles:
            if len(sources) >= cap:
                return
            part = self._read_source(archive, title, seen)
            if part is not None:
                part.origin = NAMED_ORIGIN
                sources.append(part)

    @staticmethod
    def _add_material(archive: ZimArchive, title: str, sources: list[Source], linked_to: LinkedTo) -> None:
        """The material's own article as a source of its own; one already in the corpus keeps its place (D47).

        It is read anew rather than through the articles the search has seen: a hit it dropped for lacking the topic
        in title and lead may well be the material's article, which needs no such mention.
        """
        article = archive.read(title)
        if article is None or archive.parse(article).is_disambiguation:
            return
        present = next((s for s in sources if s.project == archive.project and s.title == article.title), None)
        if present is not None:
            if not present.is_primary and present.origin in {"linked", "search", NAMED_ORIGIN}:
                present.origin = NODE_ORIGIN  # asked for: no topic filter on its paragraphs, no hit check
            return
        own = archive.to_source(article, is_primary=False)
        if linked_to(own):
            own.origin = NODE_ORIGIN
            sources.append(own)

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


def _text_length(source: Source) -> int:
    return sum(len(p.text) for s in source.sections for p in s.paragraphs)


class LinkedTo:
    """Whether an article and a fixed one - the main article of a corpus - link to one another, either way (M24).

    Links count as the archive names their targets after a redirect. M24 measured this on the corpora of real
    materials: of the 15 side articles with no link to or from the main article, 11 were unfit and none central.
    The links as written decide most pairs; only then are redirects looked up, those of the fixed article once.
    """

    def __init__(self, archive: ZimArchive, anchor: Source) -> None:
        self.archive = archive
        self.anchor = anchor
        self._targets: set[str] | None = None

    def __call__(self, other: Source) -> bool:
        if _names(self.anchor.links, other.title) or _names(other.links, self.anchor.title):
            return True
        if self._targets is None:  # resolving every link costs 10 to 300 ms per article (M25)
            self._targets = {t for link in self.anchor.links if (t := self.archive.canonical_title(link))}
        return other.title in self._targets or any(
            self.archive.canonical_title(link) == self.anchor.title for link in other.links
        )


def _names(links: Sequence[str], title: str) -> bool:
    """Whether one of the links names the title as written; a wiki title's first letter is case-free."""
    return any(link[:1].upper() + link[1:] == title for link in links)
