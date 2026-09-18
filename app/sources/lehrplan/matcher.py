"""Inference-time matching of a topic against the local curriculum cache (PLAN.md 5.3).

Keyword set: topic, aliases and sub-topics from part 1; the cache answers substring hits, the
word-boundary rule drops buried matches ("Licht" in "Wahlpflichtlernbereich"), and the ranking puts
topic areas before competencies before contents, a hit in the node's own label before one in its
parent, and levels asserted in the data before derived ones. Runs locally in milliseconds.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from app.sources.lehrplan.store import DEFAULT_SEARCH_LIMIT, MIN_KEYWORD_CHARS, LehrplanStore, NodeHit
from app.sources.lehrplan.stufen import Resolved, resolve_klassenstufe, resolve_schulstufe
from app.sources.lehrplan.vocab import ROLE_INHALT, ROLE_KOMPETENZ, ROLE_THEMENBEREICH

MIN_PART_CHARS = 4
MAX_KEYWORD_CHARS = 40
DEFAULT_MAX_KEYWORDS = 12
DEFAULT_LIMIT = DEFAULT_SEARCH_LIMIT
_ROLE_WEIGHT = {ROLE_THEMENBEREICH: 3, ROLE_KOMPETENZ: 2, ROLE_INHALT: 1}
_PARENTHESES = re.compile(r"\s*\([^)]*\)\s*$")
_WORD = r"[\wäöüÄÖÜß]"
# Parts of hyphenated titles that name a genre rather than a subject ("Säure-Base-Konzepte")
_GENERIC_PARTS = frozenset(
    {
        "konzept",
        "konzepte",
        "theorie",
        "theorien",
        "grundlagen",
        "geschichte",
        "system",
        "systeme",
        "lehre",
        "begriff",
        "begriffe",
        "einführung",
        "überblick",
        "methode",
        "methoden",
        "modell",
        "modelle",
        "wissenschaft",
    }
)


@dataclass(frozen=True)
class CurriculumMatch:
    hit: NodeHit
    keyword: str
    schulstufe: Resolved
    klassenstufe: Resolved
    score: int


@dataclass
class MatchResult:
    keywords: list[str]
    subject_terms: list[str]
    matches: list[CurriculumMatch] = field(default_factory=list)
    total_hits: int = 0
    excluded_noise: int = 0


def build_keywords(
    topic: str, *, aliases: Sequence[str], subtopics: Sequence[str], max_keywords: int = DEFAULT_MAX_KEYWORDS
) -> list[str]:
    """Topic first, then aliases and sub-topics; parenthetical qualifiers, duplicates and tiny words dropped.

    Hyphenated titles also contribute their parts ("Säure-Base-Konzepte" -> "Säure", "Base"), except
    generic ones, because curricula spell such topics as separate words.
    """
    keywords: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate((topic, *aliases, *subtopics)):
        text = _PARENTHESES.sub("", raw).strip()
        for variant in _variants(text):
            key = variant.casefold()
            # The topic itself is never dropped for length; a long title simply finds nothing.
            too_long = len(variant) > MAX_KEYWORD_CHARS and not (index == 0 and variant == text)
            if len(variant) < MIN_KEYWORD_CHARS or too_long or key in seen:
                continue
            seen.add(key)
            keywords.append(variant)
    return keywords[:max_keywords]


def _variants(text: str) -> list[str]:
    variants = [text]
    if "-" in text:
        variants.extend(
            part.strip()
            for part in text.split("-")
            if len(part.strip()) >= MIN_PART_CHARS and part.strip().casefold() not in _GENERIC_PARTS
        )
    return variants


def boundary_keyword(text: str, keywords: Sequence[str]) -> str | None:
    """The first keyword that touches a word boundary in ``text``; ``None`` when every match is buried.

    "Licht" in "Lichtbrechung" or "Kernphysik" for "Physik" count, "Licht" in "Wahlpflichtbereich" does not.
    """
    for word in keywords:
        if word and re.search(rf"(?<!{_WORD}){re.escape(word)}|{re.escape(word)}(?!{_WORD})", text, re.I):
            return word
    return None


def _score(hit: NodeHit, schulstufe: Resolved, klassenstufe: Resolved) -> int:
    role = max((_ROLE_WEIGHT.get(role, 0) for role in hit.rollen), default=0)
    own_label = 10 if hit.matched_in == "label" else 0
    from_data = 1 if (schulstufe.from_data or klassenstufe.from_data) else 0
    return role * 100 + own_label + from_data


class LehrplanMatcher:
    def __init__(self, store: LehrplanStore, *, limit: int = DEFAULT_LIMIT) -> None:
        self._store = store
        self._limit = limit

    def match(self, keywords: Sequence[str], *, subject_terms: Sequence[str] = ()) -> MatchResult:
        """Ranked curriculum elements for ``keywords``; ``subject_terms`` narrow the curricula."""
        words = [word.strip() for word in keywords if word.strip()]
        result = MatchResult(keywords=words, subject_terms=list(subject_terms))
        if not words:
            return result
        hits = self._store.search(words, subject_terms=subject_terms, limit=self._limit)
        result.total_hits = len(hits)
        for found in hits:
            # The store reports substring hits; only a keyword touching a word boundary is a real hit,
            # in the node's own label first, else in its parent label. Everything else is noise.
            keyword = boundary_keyword(found.label, words)
            matched_in = "label"
            if keyword is None:
                keyword = boundary_keyword(found.parent_label, words)
                matched_in = "parent"
            if keyword is None:
                result.excluded_noise += 1
                continue
            hit = replace(found, matched_in=matched_in)
            schulstufe = resolve_schulstufe(hit.jahrgangsstufen, hit.lehrplan)
            klassenstufe = resolve_klassenstufe(hit.jahrgangsstufen, hit.lehrplan)
            result.matches.append(
                CurriculumMatch(
                    hit=hit,
                    keyword=keyword,
                    schulstufe=schulstufe,
                    klassenstufe=klassenstufe,
                    score=_score(hit, schulstufe, klassenstufe),
                )
            )
        result.matches.sort(
            key=lambda match: (-match.score, match.hit.lehrplan.bundesland, match.hit.lehrplan.label, match.hit.label)
        )
        return result
