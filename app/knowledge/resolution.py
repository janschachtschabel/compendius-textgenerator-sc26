"""The article of a topic: the rules over the archives of a registry, and the LLM's word on them (PLAN.md 4.1).

Moved out of ``ZimRegistry`` (audit 2026-09-27, AR-03): the registry holds the archives, the knowledge package decides
which article a topic gets. ``resolve_topic`` is the one entry.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from app.domain.models import Resolution
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

if TYPE_CHECKING:
    from app.sources.zim.registry import ZimRegistry

# Meanings of a disambiguation page that are read; measured on 2026-09-23, the right one stood at place 12
# ("Schleife") and 26 ("Fall" -> Kasus), and a cap of 12 hid them
MAX_MEANINGS = 40
CHOSEN_BY_LLM = "llm"  # resolution method when article_choice=llm decided (D35)
GUESSED = frozenset({"suggestion", "search"})  # resolution methods that reach an article the name did not name
# article_choice=llm (D35): gets the (title, opening) candidates of an unsure resolution and answers with the index
# of one, or with a title of its own, or with neither; NONE_FITS is the verdict that no candidate fits (A01)
ArticleChooser = Callable[[Sequence[tuple[str, str]]], tuple[int | None, str | None]]
NONE_FITS = -1


def misses_topic(resolution: Resolution) -> bool:
    """Whether the rules missed the topic: nothing found, a title suggestion or full-text hit, or a list page.

    There the overview the LLM names replaces their article (D63, option C of the decision paper). A list page is
    reached surely, as the redirect of a group ("deutsche Dichter" -> Liste deutschsprachiger Lyriker), but carries
    little text; on the 94 gold queries these cases are 5 (M39).
    """
    title = resolution.title
    return title is None or resolution.method in GUESSED or title.startswith("Liste ")


def resolve_topic(
    registry: ZimRegistry,
    topic: str,
    context: Sequence[str] = (),
    query: str | None = None,
    terms: Sequence[str] = (),
    chooser: ArticleChooser | None = None,
    *,
    thorough: bool = False,
    overview: str | None = None,
    leading: bool = False,
) -> Resolution:
    """The article for a topic over the archives of ``registry``; see ``_Resolver.resolve_topic``."""
    return _Resolver(registry).resolve_topic(
        topic, context, query, terms, chooser, thorough=thorough, overview=overview, leading=leading
    )


class _Resolver:
    """The archives of a registry, as one resolution reads them: the leading one first."""

    def __init__(self, registry: ZimRegistry) -> None:
        self.archives: list[ZimArchive] = list(registry.archives)
        self.primary_archive: ZimArchive | None = registry.primary_archive

    def resolve_topic(
        self,
        topic: str,
        context: Sequence[str] = (),
        query: str | None = None,
        terms: Sequence[str] = (),
        chooser: ArticleChooser | None = None,
        *,
        thorough: bool = False,
        overview: str | None = None,
        leading: bool = False,
    ) -> Resolution:
        """The article for a topic: exact title, inflected form, genitive phrase, then suggestions and hits.

        ``terms`` are the words of the request's subject (``config/subjects.yaml``, ``kontext``); without them
        the words of ``context`` count, school words like "Klasse" left out. They pick the meaning of a
        disambiguation page, and they send an exact title that says nothing of the subject to the meanings of
        its "(Begriffsklärung)" page ("Informatik: Baum"). The resolution records how the title was found and
        whether that is a guess (``confident``), so a request can show the editor what to check.

        A ``chooser`` (article_choice=llm, D35) decides a guess once more, from the candidates the rules weighed.
        ``thorough`` (article_choice=llm-thorough, D61) lets it check a sure resolution of a word with several
        meanings as well: a meaning the rules took from a disambiguation page, or an exact title that has a
        "(Begriffsklärung)" page. On the 94 gold queries that was 93 instead of 91 right, and none of the 44 right
        sure resolutions it checked turned wrong (M35).

        ``overview`` is the overview article the LLM named for the topic (D63): it replaces the rules' article where
        they missed the topic (``misses_topic``), and then the chooser is not asked. Where the chooser finds that no
        candidate fits (A01), the overview takes the rules' place as well, and without one the topic has no article.
        With ``leading`` the overview replaces the rules' article wherever the archive has it: the topic is a stand-in
        for one the model heard in full (a collection with a neutral title, M71).
        """
        resolution = self._resolve_by_rules(topic, context, query, terms)
        if overview is not None and (leading or misses_topic(resolution)) and self._take_overview(resolution, overview):
            return resolution
        if chooser is None or not resolution.resolved:
            return resolution
        if not resolution.confident or (thorough and self._has_meanings(resolution)):
            self._let_choose(resolution, chooser, overview)
        return resolution

    def _has_meanings(self, resolution: Resolution) -> bool:
        """Whether a sure resolution names a word with several meanings, which the chooser then weighs (M35).

        A meaning taken from a disambiguation page has them already; for an exact title they are the meanings of
        its "(Begriffsklärung)" page, kept for the chooser.
        """
        if resolution.disambiguation:
            return True
        if resolution.method not in {"title", "variant"}:
            return False
        archive = next((a for a in self.archives if a.project == resolution.project), None)
        page = archive.read(f"{resolution.title} (Begriffsklärung)") if archive is not None else None
        if archive is None or page is None:
            return False
        parsed = archive.parse(page)
        meanings = listed_meanings(parsed)[:MAX_MEANINGS] if parsed.is_disambiguation else []
        if meanings:
            resolution._meanings = meanings
        return bool(meanings)

    def _take_overview(self, resolution: Resolution, title: str) -> bool:
        """Put the overview article in place of the rules' article, which leads the alternatives; ``False`` when the
        leading archive does not have it as an article."""
        archive = self.primary_archive
        article = archive.read_article(title) if archive is not None else None
        if archive is None or article is None or archive.parse(article).is_disambiguation:
            return False
        if resolution.title is not None and resolution.title != article.title:
            others = [t for t in resolution.alternatives if t != article.title]
            resolution.alternatives = [resolution.title, *others][:8]
        self._take(resolution, article, archive, method=CHOSEN_BY_LLM, confident=False)
        return True

    def _let_choose(self, resolution: Resolution, chooser: ArticleChooser, overview: str | None = None) -> None:
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
            article = archive.read_article(title)
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
        if index == NONE_FITS:
            self._reject(resolution, overview)
            return
        chosen, source = None, archive
        if index is not None and 0 <= index < len(articles):
            chosen = articles[index]
        elif named and self.primary_archive is not None:
            source = self.primary_archive
            found = source.read_article(named)
            chosen = found if found is not None and not source.parse(found).is_disambiguation else None
            if chosen is None:  # a title comes with the verdict that no candidate fits: it stands without one (D85)
                self._reject(resolution, overview)
                return
        if chosen is None:
            return
        if chosen.title != resolution.title:
            others = [t for t in resolution.alternatives if t != chosen.title]
            resolution.alternatives = [t for t in [resolution.title, *others] if t][:8]
        self._take(resolution, chosen, source, method=CHOSEN_BY_LLM, confident=False)

    def _reject(self, resolution: Resolution, overview: str | None) -> None:
        """The chooser found that none of the rules' candidates fits (A01): they all go, and the overview the LLM
        named takes the place where the archive has it as an article; else the topic has no article.

        Measured over 215 topics (M63): only bare words with several meanings and no subject got this verdict, and the
        rules had kept a random meaning - "Stamm (Familienname)", "Funktion (Objekt)", "Netz (Textilie)".
        """
        if overview is not None and self._take_overview(resolution, overview):
            return
        if resolution.title is not None:
            others = [t for t in resolution.alternatives if t != resolution.title]
            resolution.alternatives = [resolution.title, *others][:8]
        resolution.title = resolution.path = resolution.project = None
        resolution.method, resolution.confident = CHOSEN_BY_LLM, False

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
            found = lead.read_article(title)
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
            article = archive.read_article(title)
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
        """A meaning of "<title> (Begriffsklärung)" that speaks for the subject, when the exact article does not.

        The meaning has to name the subject in its title ("Baum (Datenstruktur)" for Informatik): one mention in its
        text is too little to overrule an exact title, and turned "Kreis" with Mathematik into "Soziale Gruppe" (M25).
        """
        page = archive.read(f"{title} (Begriffsklärung)")
        if page is None:
            return False
        parsed = archive.parse(page)
        if not parsed.is_disambiguation:
            return False
        meanings = listed_meanings(parsed)
        resolution._meanings = meanings[:MAX_MEANINGS]  # an article chooser weighs them against the exact title
        chosen, confident = self._pick_from_disambiguation(archive, meanings, stems)
        if chosen is None or not confident or not context_score(stems, chosen.title, ""):
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
            article = lead.read_article(compound)
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
            article = archive.read_article(title)
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
