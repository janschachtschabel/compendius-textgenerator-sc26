"""Registry of active archives: topic resolution and corpus construction (PLAN.md 4.1, 4.2)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from app.domain.models import Resolution, Source
from app.knowledge.related import is_blacklisted, rank_related_candidates
from app.knowledge.topic import topic_stem
from app.sources.zim.active import read_active
from app.sources.zim.archive import ZimArchive, ZimArticle
from app.sources.zim.topic_rules import (
    ASPECT_WORDS,
    LEADING_ARTICLE,
    compound_candidates,
    context_score,
    disambiguation_stems,
    inflection_variants,
    listed_meanings,
    looks_like_work,
    nominative,
    opening,
    pick_meaning,
    rank_by_query,
    split_genitive,
)
from app.templates.schema import TemplateSlot

log = logging.getLogger(__name__)

SEARCH_RESERVE = 3  # corpus slots kept for slot-targeted full-text hits
RELATED_MIN_CHARS = 350
# Meanings of a disambiguation page that are read; measured on 2026-09-23, the right one stood at place 12
# ("Schleife") and 26 ("Fall" -> Kasus), and a cap of 12 hid them
MAX_MEANINGS = 40
CHOSEN_BY_LLM = "llm"  # resolution method when article_choice=llm decided (D35)
NODE_ORIGIN = "node"  # the article of a material sent along with a topic (D47)
# article_choice=llm (D35): gets the (title, opening) candidates of an unsure resolution and answers with the index
# of one, or with a title of its own, or with neither
ArticleChooser = Callable[[Sequence[tuple[str, str]]], tuple[int | None, str | None]]


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
    def resolve_topic(
        self,
        topic: str,
        context: Sequence[str] = (),
        query: str | None = None,
        terms: Sequence[str] = (),
        chooser: ArticleChooser | None = None,
    ) -> Resolution:
        """The article for a topic: exact title, inflected form, genitive phrase, then suggestions and hits.

        ``terms`` are the words of the request's subject (``config/subjects.yaml``, ``kontext``); without them
        the words of ``context`` count, school words like "Klasse" left out. They pick the meaning of a
        disambiguation page, and they send an exact title that says nothing of the subject to the meanings of
        its "(Begriffsklärung)" page ("Informatik: Baum"). The resolution records how the title was found and
        whether that is a guess (``confident``), so a request can show the editor what to check.

        A ``chooser`` (article_choice=llm, D35) decides a guess once more, from the candidates the rules weighed.
        """
        resolution = self._resolve_by_rules(topic, context, query, terms)
        if chooser is not None and resolution.resolved and not resolution.confident:
            self._let_choose(resolution, chooser)
        return resolution

    def _let_choose(self, resolution: Resolution, chooser: ArticleChooser) -> None:
        """Let the chooser decide an unsure resolution; its answer replaces the rules' article when it is one.

        The candidates are the meanings of the disambiguation page in their order, or else the rules' article
        first, then the meanings its subject check read and the other suggestions and hits.
        """
        archive = next((a for a in self.archives if a.project == resolution.project), None)
        if archive is None:
            return
        meanings = resolution._meanings
        if resolution.method == "disambiguation" and meanings:
            titles = meanings
        else:
            titles = [t for t in dict.fromkeys([resolution.title, *meanings, *resolution.alternatives]) if t]
        candidates: list[tuple[str, str]] = []
        articles: list[ZimArticle] = []
        for title in titles:
            article = archive.read(title)
            if article is None:
                continue
            parsed = archive.parse(article)
            if parsed.is_disambiguation or any(parsed.title == known for known, _ in candidates):
                continue
            candidates.append((parsed.title, opening(parsed.text)))
            articles.append(article)
        if not candidates:
            return
        index, named = chooser(candidates)
        chosen, source = None, archive
        if index is not None and 0 <= index < len(articles):
            chosen = articles[index]
        elif named and self.primary_archive is not None:
            source = self.primary_archive
            found = source.read(named)
            chosen = found if found is not None and not source.parse(found).is_disambiguation else None
        if chosen is None:
            return
        if chosen.title != resolution.title:
            others = [t for t in resolution.alternatives if t != chosen.title]
            resolution.alternatives = [t for t in [resolution.title, *others] if t][:8]
        self._take(resolution, chosen, source, method=CHOSEN_BY_LLM, confident=False)

    def _resolve_by_rules(
        self, topic: str, context: Sequence[str], query: str | None, terms: Sequence[str]
    ) -> Resolution:
        resolution = Resolution(query=query or topic, normalized=topic, context=list(context))
        stems = disambiguation_stems(terms) if terms else disambiguation_stems(context)
        if self._resolve_exact(topic, stems, resolution, method="title"):
            return resolution
        for variant in inflection_variants(topic):
            if self._resolve_exact(variant, stems, resolution, method="variant"):
                return resolution
        genitive = split_genitive(topic)
        if genitive is not None:
            head, tail = genitive
            if head.lower() in ASPECT_WORDS:
                # "Ursachen der Französischen Revolution": the article is the revolution, a guess at the request
                inner = self._resolve_by_rules(nominative(tail), context, query or topic, terms)
                if inner.resolved:
                    method = "variant" if inner.method == "title" else inner.method
                    return inner.model_copy(update={"normalized": topic, "method": method, "confident": False})
            elif self._resolve_compound(head, tail, resolution):
                return resolution
        lead = self.primary_archive
        if lead is None:
            return resolution
        suggestions = [t for t in lead.suggest(topic, 10) if "(begriffsklärung)" not in t.lower()]
        hits = lead.search(topic, 5)
        exact = [t for t in suggestions if t.lower() == topic.lower()]
        ranked = rank_by_query(topic, [*suggestions, *hits])
        candidates = list(dict.fromkeys([*exact, *([ranked] if ranked else []), *suggestions, *hits]))
        for title in candidates:
            found = lead.read(title)
            if found is None or lead.parse(found).is_disambiguation:
                continue
            resolution.alternatives = [t for t in candidates if t != title][:8]
            method = "suggestion" if title in suggestions else "search"
            self._take(resolution, found, lead, method=method, confident=False)
            return resolution
        return resolution

    def _resolve_exact(self, title: str, stems: set[str], resolution: Resolution, *, method: str) -> bool:
        """Resolve through an exact title (redirects followed) in the archives, leading archive first."""
        for archive in self.archives:
            article = archive.read(title)
            if article is None:
                continue
            parsed = archive.parse(article)
            if parsed.is_disambiguation:
                resolution.disambiguation = True
                meanings = listed_meanings(parsed)  # one list: what is offered is what is chosen from
                resolution.alternatives = meanings[:8]
                resolution._meanings = meanings[:MAX_MEANINGS]
                chosen, confident = self._pick_from_disambiguation(archive, meanings, stems)
                if chosen is not None:
                    self._take(resolution, chosen, archive, method="disambiguation", confident=confident)
                    return True
                continue
            fits = not stems or context_score(stems, parsed.title, parsed.text) > 0
            if not fits and self._meaning_for_subject(archive, parsed.title, stems, resolution):
                return True
            article_less = LEADING_ARTICLE.match(title)
            if method == "title" and article_less and looks_like_work(parsed.text):
                # "Die Französische Revolution" is a film; the topic without its article is the revolution
                if self._resolve_exact(article_less.group(1), stems, resolution, method="title"):
                    resolution.alternatives = [parsed.title, *resolution.alternatives][:8]
                    return True
            # An article that names nothing of the subject may still be right, but it is a guess ("Erdkunde: Delta")
            self._take(resolution, article, archive, method=method, confident=fits)
            return True
        return False

    def _meaning_for_subject(self, archive: ZimArchive, title: str, stems: set[str], resolution: Resolution) -> bool:
        """A meaning of "<title> (Begriffsklärung)" that speaks for the subject, when the exact article does not."""
        page = archive.read(f"{title} (Begriffsklärung)")
        if page is None:
            return False
        parsed = archive.parse(page)
        if not parsed.is_disambiguation:
            return False
        meanings = listed_meanings(parsed)
        resolution._meanings = meanings[:MAX_MEANINGS]  # an article chooser weighs them against the exact title
        chosen, confident = self._pick_from_disambiguation(archive, meanings, stems)
        if chosen is None or not confident:
            return False
        resolution.disambiguation = True
        resolution.alternatives = [title, *(m for m in meanings if m != chosen.title)][:8]
        self._take(resolution, chosen, archive, method="disambiguation", confident=True)
        return True

    def _resolve_compound(self, head: str, tail: str, resolution: Resolution) -> bool:
        """ "Kreislauf des Wassers" -> "Wasserkreislauf": the compound of a genitive phrase, when it is an article."""
        lead = self.primary_archive
        if lead is None:
            return False
        for compound in compound_candidates(head, tail):
            article = lead.read(compound)
            if article is not None and not lead.parse(article).is_disambiguation:
                self._take(resolution, article, lead, method="variant", confident=False)
                return True
        return False

    def _pick_from_disambiguation(
        self, archive: ZimArchive, links: Sequence[str], stems: set[str]
    ) -> tuple[ZimArticle | None, bool]:
        """The meaning the context speaks for (``pick_meaning``) and whether that is sure.

        Without context the first real article of the list is taken, and that is a guess.
        """
        articles: list[ZimArticle] = []
        meanings: list[tuple[str, str]] = []
        for title in links[:MAX_MEANINGS]:
            article = archive.read(title)
            if article is None:
                continue
            parsed = archive.parse(article)
            if parsed.is_disambiguation:
                continue
            if not stems:
                return article, False
            articles.append(article)
            meanings.append((parsed.title, parsed.text))
        if not articles:
            return None, False
        index, confident = pick_meaning(meanings, stems)
        return articles[index], confident

    @staticmethod
    def _take(
        resolution: Resolution, article: ZimArticle, archive: ZimArchive, *, method: str, confident: bool
    ) -> None:
        resolution.title, resolution.path, resolution.project = article.title, article.path, archive.project
        resolution.method, resolution.confident = method, confident

    # -- corpus ------------------------------------------------------------------------------------
    def build_corpus(
        self, resolution: Resolution, slots: Sequence[TemplateSlot], max_articles: int, material: str | None = None
    ) -> list[Source]:
        """The main article, its twin, linked sub-articles and full-text hits for the blocks, at most ``max_articles``.

        ``material`` is the own article of a material sent along with a topic (D47): it joins as a source of its own
        (origin ``node``) when it links with the main article, beyond ``max_articles`` like the twin.
        """
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

        linked_to = LinkedTo(primary_archive, primary)
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
            # M25: of the hits with no link to or from the main article most were unfit; without them the printed
            # unfit paragraphs of 20 topics fell from 25 to 12. Their places stay empty, as measured.
            sources = [s for s in sources if s.origin != "search" or linked_to(s)]
        if material and material != primary.title:
            self._add_material(primary_archive, material, sources, seen, linked_to)
        return sources

    def _add_material(
        self,
        archive: ZimArchive,
        title: str,
        sources: list[Source],
        seen: set[tuple[str, str]],
        linked_to: LinkedTo,
    ) -> None:
        """The material's own article as a source of its own; one already in the corpus keeps its place (D47)."""
        present = next((s for s in sources if s.project == archive.project and s.title == title), None)
        if present is not None:
            if not present.is_primary and present.origin in {"linked", "search"}:
                present.origin = NODE_ORIGIN  # asked for: no topic filter on its paragraphs, no hit check
            return
        own = self._read_source(archive, title, seen)
        if own is not None and linked_to(own):
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
