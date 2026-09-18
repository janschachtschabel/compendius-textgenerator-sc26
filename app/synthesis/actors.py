"""Generated block: actor directory (person, organisation, project, network) from linked articles."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.domain.models import Source
from app.knowledge.entities import classify_entity
from app.knowledge.segmentation import split_sentences

Lookup = Callable[[str], Source | None]

_DEATH_RE = re.compile(r"†\s*(?:\d{1,2}\.\s*)?\w*\s*(\d{3,4})")

_FUNCTION_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\b(Universität|Hochschule|Institut|Forschung|Akademie|Wissenschaft|Labor)", re.IGNORECASE),
        "Wissenschaft & Entwicklung",
    ),
    (
        re.compile(r"\b(Behörde|Ministerium|Bundesamt|Norm|Aufsicht|Gesetz|Regulierung|Kammer)", re.IGNORECASE),
        "Rahmensetzung",
    ),
    (re.compile(r"\b(Schule|Ausbildung|Lehre|Unterricht|Bildung|Didaktik|Lehrer)", re.IGNORECASE), "Bildung"),
    (
        re.compile(
            r"\b(Verband|Verein|Gesellschaft|Netzwerk|Verbund|Community|Fachgesellschaft|Kooperation)", re.IGNORECASE
        ),
        "Vernetzung & Fachgebietsentwicklung",
    ),
]

TYPE_ORDER = ["Person", "Organisation", "Vorhaben", "Netzwerk"]


@dataclass
class Actor:
    name: str
    kind: str
    summary: str
    url: str
    functions: list[str]
    zeitbezug: str


def classify(source: Source) -> str | None:
    """Cascade: person, organisation, project, network; first match wins; else not an actor."""
    return classify_entity(source)


def _functions(text: str, kind: str) -> list[str]:
    found = [label for pattern, label in _FUNCTION_RULES if pattern.search(text)]
    if not found and kind == "Person":
        found = ["Wissenschaft & Entwicklung"]
    return found[:2] if found else ["Vernetzung & Fachgebietsentwicklung"]


def _zeitbezug(lead: str) -> str:
    match = _DEATH_RE.search(lead)
    if match:
        return "historisch"
    years = [int(y) for y in re.findall(r"\b(1[0-9]{3}|20[0-9]{2})\b", lead[:200])]
    if years and max(years) < 1950:
        return "historisch"
    return "gegenwärtig"


def _summary(source: Source) -> str:
    sentences = split_sentences(source.lead_text)
    text = sentences[0] if sentences else source.title
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= 260 else text[:257] + "…"


def candidate_links(primary: Source, preferred_headings: set[str]) -> list[str]:
    """Links of the primary article, those from actor-like sections (e.g. 'Bekannte …') first."""
    preferred: list[str] = []
    others: list[str] = []
    for section in primary.sections:
        bucket = preferred if section.heading in preferred_headings else others
        bucket.extend(section.links)
    ordered = preferred + others + primary.links
    return list(dict.fromkeys(ordered))


def collect_actors(
    primary: Source | None,
    sources: Sequence[Source],
    lookup: Lookup | None,
    max_lookups: int = 40,
    preferred_headings: set[str] | None = None,
) -> list[Actor]:
    """Actors among corpus sources plus linked articles of the primary article."""
    candidates: list[Source] = [s for s in sources if not s.is_primary]
    seen = {s.title.lower() for s in candidates}
    if primary is not None and lookup is not None:
        lookups = 0
        for title in candidate_links(primary, preferred_headings or set()):
            if lookups >= max_lookups:
                break
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            lookups += 1
            found = lookup(title)
            if found is not None:
                candidates.append(found)

    actors: list[Actor] = []
    for source in candidates:
        kind = classify(source)
        if kind is None:
            continue
        lead = source.lead_text
        actors.append(
            Actor(
                name=source.title,
                kind=kind,
                summary=_summary(source),
                url=source.url,
                functions=_functions(lead[:600], kind),
                zeitbezug=_zeitbezug(lead),
            )
        )
    actors.sort(key=lambda a: (TYPE_ORDER.index(a.kind), a.name.lower()))
    return actors


def build_actors_section(actors: Sequence[Actor], facets_visible: bool) -> str:
    if not actors:
        return ""
    lines = ["Akteure aus den herangezogenen Artikeln, nach Kaskadentyp; Namen verweisen auf den Quellartikel.", ""]
    for kind in TYPE_ORDER:
        group = [a for a in actors if a.kind == kind]
        if not group:
            continue
        lines.append(f"#### {kind}")
        lines.append("")
        for actor in group:
            facet = (
                f" [Akteursfunktion: {', '.join(actor.functions)}] [Zeitbezug: {actor.zeitbezug}]"
                if facets_visible
                else ""
            )
            lines.append(f"- **[{actor.name}]({actor.url})** — {actor.summary}{facet}")
        lines.append("")
    return "\n".join(lines).rstrip()
