"""Part 2 for one compendium: keywords from part 1, subject terms, local match, rendering (PLAN.md 5.3, 5.4)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from app.domain.models import CurriculaPart
from app.sources.lehrplan.matcher import CurriculumMatch, LehrplanMatcher, build_keywords
from app.sources.lehrplan.render import RenderOptions, render_curricula, render_missing_cache
from app.sources.lehrplan.store import LehrplanCacheError, LehrplanStore
from app.sources.lehrplan.subjects import SubjectCatalog

log = logging.getLogger(__name__)

MAX_ENTRIES = 200


def match_entry(match: CurriculumMatch) -> dict[str, Any]:
    """One match as a flat record for the JSON answer and the search endpoint."""
    lehrplan = match.hit.lehrplan
    return {
        "iri": match.hit.iri,
        "label": match.hit.label,
        "rollen": list(match.hit.rollen),
        "bereich": match.hit.parent_label,
        "lehrplan": lehrplan.label,
        "lehrplan_iri": lehrplan.iri,
        "bundesland": lehrplan.bundesland,
        "bundesland_code": lehrplan.bundesland_code,
        "schulart": lehrplan.schularten[0] if lehrplan.schularten else None,
        "schulfaecher": list(lehrplan.schulfaecher),
        "schulstufe": match.schulstufe.value,
        "schulstufe_quelle": match.schulstufe.source,
        "klassenstufe": match.klassenstufe.value,
        "klassenstufe_quelle": match.klassenstufe.source,
        "keyword": match.keyword,
        "score": match.score,
    }


@dataclass(frozen=True)
class CurriculaBuilder:
    """Everything part 2 needs at inference time: the cache, the subject mapping, the length budget."""

    store: LehrplanStore
    subjects: SubjectCatalog
    options: RenderOptions = field(default_factory=RenderOptions)

    def build(
        self,
        *,
        title: str,
        aliases: Sequence[str],
        subtopics: Sequence[str],
        subject: str | None,
        facets_visible: bool,
    ) -> CurriculaPart:
        keywords = build_keywords(title, aliases=aliases, subtopics=subtopics)
        subject_terms = self.subjects.mem_terms(subject)
        if not self.store.available:
            return CurriculaPart(
                available=False,
                keywords=keywords,
                subject_terms=subject_terms,
                summary={"reason": "cache_missing", "db_path": str(self.store.path)},
                markdown=render_missing_cache(),
            )
        try:
            result = LehrplanMatcher(self.store).match(keywords, subject_terms=subject_terms)
        except LehrplanCacheError as exc:  # part 2 degrades to the hint; parts 1 and 3 are not lost
            log.error("%s", exc)
            return CurriculaPart(
                available=False,
                keywords=keywords,
                subject_terms=subject_terms,
                summary={"reason": "cache_unreadable"},
                markdown=render_missing_cache(),
            )
        markdown, summary = render_curricula(
            result, meta=self.store.meta(), options=replace(self.options, facets_visible=facets_visible)
        )
        return CurriculaPart(
            available=True,
            keywords=result.keywords,
            subject_terms=result.subject_terms,
            summary=summary,
            entries=[match_entry(match) for match in result.matches[:MAX_ENTRIES]],
            markdown=markdown,
        )
