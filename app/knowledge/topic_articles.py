"""The question N (D63): the LLM names the overview article of a topic and the articles on its parts.

A compendium builds on one main article and the side articles its links and the full-text search bring; a topic that
is a group or joins two subjects ("deutsche Dichter", "Klimawandel und Landwirtschaft") has no article of its own. In
M37 (docs/entwicklung/05-messprotokoll.md) the model named the overview - for a group the epoch, genre or general
term, no list - and up to eight articles on the most important members, parts or aspects. Built from them, 87 instead
of 45 % of the printed paragraphs came from fitting articles on 25 such topics, 93 instead of 73 % on 20 ordinary
ones, at about 500 tokens and 3.5 s. Without an LLM neither spaCy's entities nor the archive's structure reached
that (M38).

The titles are looked up as measured: as the archive has them (a redirect counts as its target), else in the old
service's spelling variants; a disambiguation page, a title the archive lacks and a repeat drop out. Whatever keeps the
model from naming an article of the archive - b-api, budget, time, an unreadable answer - leaves the corpus of before,
and the reason goes to the audit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.domain.models import Source
from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob, Usage, read_object
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.prompts import get_prompt
from app.sources.zim.archive import ZimArchive
from app.sources.zim.registry import NAMED_ORIGIN

MAX_NAMED = 8  # articles on the parts, besides the overview (M37)
OUTPUT_TOKENS = 600  # as measured; the reasoning room of the model comes on top (budgeted_chat)
NONE_FOUND = "kein genannter Titel ist ein Artikel des Archivs"
NO_PARTS = "kein genannter Teil ist ein Artikel des Archivs; Nebenartikel wie ohne die Frage"


@dataclass
class TopicArticlesReport(Usage):
    """What the model named for a topic and which of it the archive has (D63), for the audit.

    ``found`` starts with the overview when the archive has it (``overview_title``); without it the first part found
    stands in for the overview, as measured (M37: "Philosophen der Aufklärung" -> John Locke).
    """

    overview: str | None = None  # the overview article as the model named it
    named: list[str] = field(default_factory=list)  # the articles on the parts, as named
    found: list[str] = field(default_factory=list)  # the archive's titles, the overview (when found) first
    overview_title: str | None = None  # the overview as the archive has it; None when it does not
    main: bool = False  # the first title found replaced the main article of the rules (registry.misses_topic)
    parts: int = 0  # named articles the corpus took (``settle``)
    fallback: str | None = None  # why the question left the corpus of before


def ask_topic_articles(
    job: ArticleChoiceJob, archive: ZimArchive, topic: str, subjects: Sequence[str] = ()
) -> TopicArticlesReport:
    """Ask the model for the articles of ``topic`` and look them up in ``archive``, the leading one.

    ``subjects`` are the labels of the request's subjects: the model hears them after the topic, as the rules and the
    choice of an unsure article do, so "Baum" in Informatik names data structures, not trees.
    """
    report = TopicArticlesReport()
    prompt = get_prompt("topic_articles")
    heard = f"{topic} (Fach: {', '.join(subjects)})" if subjects else topic
    answer = budgeted_chat(
        job.client,
        prompt.render(topic=heard, count=MAX_NAMED),
        max_output_tokens=OUTPUT_TOKENS,
        budget=job.budget,
        what="Artikel des Themas",
        deadline=job.deadline,
    )
    report.count(answer, prompt.tag)
    if isinstance(answer, LlmSkipped):
        report.fallback = answer.reason
        return report
    data = read_object(answer.text)
    if data is None:
        report.fallback = UNREADABLE
        return report
    report.overview = str(data.get("uebersicht") or "").strip() or None
    parts = data.get("artikel")
    report.named = [str(t).strip() for t in parts if str(t).strip()][:MAX_NAMED] if isinstance(parts, list) else []
    report.overview_title = _look_up(archive, report.overview) if report.overview else None
    for label in [report.overview, *report.named] if report.overview else report.named:
        title = _look_up(archive, label)
        if title is not None and title not in report.found:
            report.found.append(title)
    if not report.found:
        report.fallback = NONE_FOUND
    return report


def settle(report: TopicArticlesReport, sources: Sequence[Source]) -> None:
    """What the corpus took of the answer: without a named article of its own, it kept the side articles of before."""
    report.parts = sum(1 for source in sources if source.origin == NAMED_ORIGIN)
    if report.found and not report.parts and report.fallback is None:
        report.fallback = NO_PARTS


def _look_up(archive: ZimArchive, label: str) -> str | None:
    """The article behind a label as M37 found it: the label, then its spelling variants; a disambiguation is none."""
    for candidate in [label, *_spellings(label)]:
        article = archive.read_article(candidate)
        if article is not None:
            return None if archive.parse(article).is_disambiguation else article.title
    return None


def _spellings(name: str) -> list[str]:
    """The old service's spelling variants (fallbacks/strategies.py), tried as M37 tried them."""
    found = [name.title(), name.lower(), name.upper()]
    found += [name[4:] for article in ("Der ", "Die ", "Das ") if name.startswith(article)]
    found += [name.replace("ß", "ss"), name.replace("ä", "ae"), name.replace("ö", "oe"), name.replace("ü", "ue")]
    return [v for v in dict.fromkeys(found) if v != name]
