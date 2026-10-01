"""Knowledge collection (PLAN.md 6.3): the materials of a collection become sources for part 1.

Every material counts, whatever its licence (Jan, 2026-10-01, D70: the service is built for editorial teams with
content of their own). By default a material brings what its metadata says, its description; with ``fulltext`` its
extracted text as well, cached for a week, fetched a few at a time. A failing material never fails the compendium:
it is listed in the result so the audit can say what is missing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from app.concurrency import map_in_threads
from app.domain.models import ArticleSection, Paragraph, Source, SourceRole
from app.domain.spelling import readable
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingError, Remaining, spent
from app.sources.wlo.errors import TimeUpError
from app.sources.wlo.models import MaterialRef

log = logging.getLogger(__name__)

PROJECT = "wlo_material"
# Not "Inhalt": the heading lexicon excludes that heading (a table of contents), which turned every material text
# into reference lines and left only the description for part 1. Measured 2026-09-23 (collection Optik, staging, six
# materials with text): 6 chunks before, 73 now (67 from the texts), one of them printed. The name hits no pattern of
# the lexicon, the facets or the slot exclusions.
TEXT_HEADING = "Materialtext"
MIN_PARAGRAPH_CHARS = 40
TIME_UP = "Zeitbudget der Anfrage erschöpft"  # compared by identity in material_sources
# Consent banners and cookie notices crawled from the material's page are not knowledge
_CONSENT = re.compile(r"cookie|consent|store and/or access information|datenschutzeinstellungen", re.IGNORECASE)


class TextClient(Protocol):
    scope: str  # whose answers its texts are, the repository and the account (EduSharingClient.scope)

    def text_content(self, node_id: str, *, remaining: Remaining | None = None) -> str: ...


@dataclass(frozen=True)
class KnowledgeOptions:
    max_materials: int = 30
    max_chars: int = 20_000
    concurrency: int = 4
    text_ttl_s: float = 7 * 86_400


@dataclass
class KnowledgeResult:
    sources: list[Source] = field(default_factory=list)
    considered: int = 0
    empty: int = 0  # brought no paragraph: no description long enough, and no text or none asked for
    failed: list[str] = field(default_factory=list)
    timed_out: int = 0  # not fetched because the request's time budget was spent
    collections: int = 1  # the collection and the sub-collections read with it (knowledge_depth)


def paragraphs_from_text(text: str, max_chars: int) -> list[str]:
    """Paragraphs worth citing: one per line, long enough to be a sentence, no consent boilerplate; in one spelling,
    as the archives write theirs (app/domain/spelling.py)."""
    paragraphs: list[str] = []
    total = 0
    for raw in text.splitlines():
        line = readable(" ".join(raw.split()))
        if len(line) < MIN_PARAGRAPH_CHARS or _CONSENT.search(line):
            continue
        if paragraphs and total + len(line) > max_chars:
            break
        paragraphs.append(line)
        total += len(line)
    return paragraphs


def _source(ref: MaterialRef, paragraphs: list[str]) -> Source:
    sections: list[ArticleSection] = []
    if len(ref.description) >= MIN_PARAGRAPH_CHARS:
        sections.append(ArticleSection(heading="", path=[], level=0, paragraphs=[Paragraph(text=ref.description)]))
    if paragraphs:
        sections.append(
            ArticleSection(
                heading=TEXT_HEADING, path=[TEXT_HEADING], level=2, paragraphs=[Paragraph(text=p) for p in paragraphs]
            )
        )
    return Source(
        source_id=f"wlo:{ref.id}",
        project=PROJECT,
        role=SourceRole.MATERIAL,
        title=ref.title or ref.id,
        url=ref.url,
        license=ref.license,
        authors=list(ref.authors),
        authority_score=0.8,
        is_primary=False,
        origin="material",
        sections=sections,
    )


def material_sources(
    client: TextClient,
    cache: TtlCache | None,
    refs: list[MaterialRef],
    *,
    options: KnowledgeOptions,
    remaining: Remaining | None = None,
    fulltext: bool = False,
) -> KnowledgeResult:
    """Sources for the materials of a collection: their descriptions, with ``fulltext`` their texts as well, fetched
    in parallel within the budget.

    ``remaining`` gives the seconds left of the request's time budget: texts not in the cache are no longer fetched
    once it is spent, and none waits longer than it, so a slow repository cannot hold the request for 30 materials
    times the client timeout. A text still on its way when the budget ends counts as not fetched in time.
    """
    result = KnowledgeResult()
    chosen = refs[: options.max_materials]
    result.considered = len(chosen)
    if not fulltext:  # what the listing already says: no request for any text
        for ref in chosen:
            if len(ref.description) >= MIN_PARAGRAPH_CHARS:
                result.sources.append(_source(ref, []))
            else:
                result.empty += 1
        return result

    def fetch(ref: MaterialRef) -> tuple[MaterialRef, str | None, str | None]:
        # the same id may name another text in another repository or for another account (audit 2026-09-29, A03)
        key = f"text:{client.scope}:{ref.id}"
        cached = cache.get(key) if cache is not None else None
        if isinstance(cached, str):
            return ref, cached, None
        if spent(remaining):
            return ref, None, TIME_UP
        try:
            text = client.text_content(ref.id, remaining=remaining)
        except TimeUpError:
            return ref, None, TIME_UP
        except EduSharingError as exc:
            return ref, None, str(exc)
        if cache is not None:
            cache.set(key, text, ttl_s=options.text_ttl_s)
        return ref, text, None

    outcomes = map_in_threads(fetch, chosen, options.concurrency)  # the log lines keep the request id
    for ref, text, error in outcomes:
        if error is TIME_UP:
            result.timed_out += 1
            continue
        if error is not None:
            log.warning("material %s (%s) could not be read: %s", ref.id, ref.title, error)
            result.failed.append(ref.id)
            continue
        paragraphs = paragraphs_from_text(text or "", options.max_chars)
        if not paragraphs and len(ref.description) < MIN_PARAGRAPH_CHARS:
            result.empty += 1
            continue
        result.sources.append(_source(ref, paragraphs))
    return result
