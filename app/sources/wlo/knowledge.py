"""Knowledge collection (PLAN.md 6.3): the materials of a collection become sources for part 1.

Only materials under a licence that allows verbatim reuse are fetched (``EXTRACTIVE_LICENSES``); the
extracted text of each is cached for a week, fetched a few at a time, and a failing material never
fails the compendium: it is listed in the result so the audit can say what is missing.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.models import ArticleSection, Paragraph, Source, SourceRole
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingError
from app.sources.wlo.models import MaterialRef, is_extractive, license_label

log = logging.getLogger(__name__)

PROJECT = "wlo_material"
MIN_PARAGRAPH_CHARS = 40
# Consent banners and cookie notices crawled from the material's page are not knowledge
_CONSENT = re.compile(r"cookie|consent|store and/or access information|datenschutzeinstellungen", re.IGNORECASE)


class TextClient(Protocol):
    def text_content(self, node_id: str) -> str: ...


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
    skipped_license: int = 0
    empty: int = 0
    failed: list[str] = field(default_factory=list)


def paragraphs_from_text(text: str, max_chars: int) -> list[str]:
    """Paragraphs worth citing: one per line, long enough to be a sentence, no consent boilerplate."""
    paragraphs: list[str] = []
    total = 0
    for raw in text.splitlines():
        line = " ".join(raw.split())
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
    sections.append(
        ArticleSection(heading="Inhalt", path=["Inhalt"], level=2, paragraphs=[Paragraph(text=p) for p in paragraphs])
    )
    return Source(
        source_id=f"wlo:{ref.id}",
        project=PROJECT,
        role=SourceRole.MATERIAL,
        title=ref.title or ref.id,
        url=ref.url,
        license=license_label(ref.license_key),
        authority_score=0.8,
        is_primary=False,
        origin="material",
        sections=sections,
    )


def material_sources(
    client: TextClient, cache: TtlCache | None, refs: list[MaterialRef], *, options: KnowledgeOptions
) -> KnowledgeResult:
    """Sources for the reusable materials of a collection, fetched in parallel within the budget."""
    result = KnowledgeResult()
    allowed = [ref for ref in refs if is_extractive(ref.license_key)]
    result.skipped_license = len(refs) - len(allowed)
    chosen = allowed[: options.max_materials]
    result.considered = len(chosen)

    def fetch(ref: MaterialRef) -> tuple[MaterialRef, str | None, str | None]:
        key = f"text:{ref.id}"
        cached = cache.get(key) if cache is not None else None
        if isinstance(cached, str):
            return ref, cached, None
        try:
            text = client.text_content(ref.id)
        except EduSharingError as exc:
            return ref, None, str(exc)
        if cache is not None:
            cache.set(key, text, ttl_s=options.text_ttl_s)
        return ref, text, None

    with ThreadPoolExecutor(max_workers=max(1, options.concurrency)) as pool:
        outcomes = list(pool.map(fetch, chosen))
    for ref, text, error in outcomes:
        if error is not None:
            log.warning("material %s (%s) could not be read: %s", ref.id, ref.title, error)
            result.failed.append(ref.id)
            continue
        paragraphs = paragraphs_from_text(text or "", options.max_chars)
        if not paragraphs:
            result.empty += 1
            continue
        result.sources.append(_source(ref, paragraphs))
    return result
