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

from dataclasses import dataclass, field

from app.knowledge.article_choice import UNREADABLE, ArticleChoiceJob, Usage, read_object
from app.llm.call import LlmSkipped, budgeted_chat
from app.llm.prompts import get_prompt
from app.sources.zim.archive import ZimArchive

MAX_NAMED = 8  # articles on the parts, besides the overview (M37)
OUTPUT_TOKENS = 600  # as measured; the reasoning room of the model comes on top (budgeted_chat)
NONE_FOUND = "kein genannter Titel ist ein Artikel des Archivs"


@dataclass
class TopicArticlesReport(Usage):
    """What the model named for a topic and which of it the archive has (D63), for the audit."""

    overview: str | None = None  # the overview article as the model named it
    named: list[str] = field(default_factory=list)  # the articles on the parts, as named
    found: list[str] = field(default_factory=list)  # the archive's titles, the overview (when found) first
    main: bool = False  # the overview replaced the main article of the rules (registry.misses_topic)
    fallback: str | None = None  # why no article of the archive came of the question


def ask_topic_articles(job: ArticleChoiceJob, archive: ZimArchive, topic: str) -> TopicArticlesReport:
    """Ask the model for the articles of ``topic`` and look them up in ``archive``, the leading one."""
    report = TopicArticlesReport()
    prompt = get_prompt("topic_articles")
    answer = budgeted_chat(
        job.client,
        prompt.render(topic=topic, count=MAX_NAMED),
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
    report.found = _looked_up(archive, [report.overview, *report.named] if report.overview else report.named)
    if not report.found:
        report.fallback = NONE_FOUND
    return report


def _looked_up(archive: ZimArchive, labels: list[str]) -> list[str]:
    titles: list[str] = []
    for label in labels:
        for candidate in [label, *_spellings(label)]:
            article = archive.read_article(candidate)
            if article is not None:
                if not archive.parse(article).is_disambiguation and article.title not in titles:
                    titles.append(article.title)
                break
    return titles


def _spellings(name: str) -> list[str]:
    """The old service's spelling variants (fallbacks/strategies.py), tried as M37 tried them."""
    found = [name.title(), name.lower(), name.upper()]
    found += [name[4:] for article in ("Der ", "Die ", "Das ") if name.startswith(article)]
    found += [name.replace("ß", "ss"), name.replace("ä", "ae"), name.replace("ö", "oe"), name.replace("ü", "ue")]
    return [v for v in dict.fromkeys(found) if v != name]
