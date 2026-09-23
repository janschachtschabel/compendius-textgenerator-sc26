"""Rank internal links of the main article as candidates for the corpus (topic independent)."""

from __future__ import annotations

import re

from app.domain.models import Source

_BLACKLIST: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r".*(sprache|dialekt|mundart|grammatik|konsonant|vokal|schrift|alphabet|etymologie|wiktionary).*",
        r"^(altgriechisch|neugriechisch|griechisch|latein|lateinisch|deutsch|englisch|französisch|hebräisch|arabisch).*$",
        r"^(physik|chemie|biologie|mathematik|informatik|wirtschaft|volkswirtschaft|betriebswirtschaft|soziologie|"
        r"psychologie|gesellschaft|medizin|philosophie|geisteswissenschaft|wissenschaft|naturwissenschaft|technik|"
        r"ingenieurwissenschaft|kunst|kultur|natur|mensch|welt|erde)$",
        r"^\d{1,4}$",
        r".*jahrhundert.*",
        r"^(antike|mittelalter|neuzeit|urgeschichte|frühgeschichte|moderne|gegenwart)$",
        r"^(liste |portal:|kategorie:|hilfe:|wikipedia:|vorlage:|datei:|spezial:|diskussion:).*",
        r"^(europa|deutschland|österreich|schweiz|frankreich|italien|england|usa|vereinigte staaten|rom|berlin)$",
        r"^(internationale einheitensystem|si-einheit|meter|sekunde|kilogramm)$",
    )
]

_WORD = re.compile(r"[a-zäöüß]{4,}")


def _stems(title: str) -> list[str]:
    words = set(_WORD.findall(title.lower()))
    return [w[:-1] if len(w) > 5 else w for w in words]


def is_blacklisted(title: str, topic: str | None = None) -> bool:
    """Meta pages, list articles, languages, bare years and umbrella terms never enter a corpus.

    A pattern the ``topic`` matches itself does not count, so a language topic keeps its language articles. It used
    to waive every pattern: "Programmiersprache" matched the language one and let "Liste von Programmiersprachen"
    in (M8, 2026-09-23).
    """
    key = title.strip().lower()
    waived = topic.strip().lower() if topic else ""
    return any(p.search(key) and not (waived and p.search(waived)) for p in _BLACKLIST)


def rank_related_candidates(main: Source, candidates: list[str]) -> list[str]:
    """Return candidate titles ordered by topical closeness to the main article."""
    main_title = main.title.lower()
    content = "\n".join(p.text for s in main.sections for p in s.paragraphs)
    content_lower = content.lower()
    headings = {h.lower() for s in main.sections for h in s.path}
    stems = _stems(main.title)
    topic_words = set(_WORD.findall(main_title))

    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for raw in candidates:
        link = raw.strip().replace("_", " ")
        key = link.lower()
        if not link or key in seen or key == main_title:
            continue
        seen.add(key)
        if is_blacklisted(key, topic=main_title):
            continue
        score = 0.0
        if any(stem in key for stem in stems):
            score += 12.0
        elif any(w in key for w in topic_words):
            score += 8.0
        if any(key == h or key in h or h in key for h in headings):
            score += 7.0
        if len(link) >= 3:
            mentions = len(re.findall(re.escape(key), content_lower))
            score += min(mentions, 8) * 1.5
        if 4 <= len(link) <= 40:
            score += 1.0
        if score > 0:
            scored.append((score, link))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [title for _, title in scored]
