"""Facet declaration and rule-based annotation (PLAN.md 4.6, decision D13).

Part 1 facets are best effort. ``minimal`` annotates Zeitbezug, Bildungsstufe and Evidenzgrad;
``full`` adds the remaining declared facets. Values never go beyond what the text or the source
role supports; missing required facets are reported by the lint step, not invented.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.domain.models import Chunk, Source
from app.templates.schema import TemplateSlot


class FacetDeclaration(BaseModel):
    values: list[str] = Field(default_factory=list)
    allowed_slots: list[str] = Field(default_factory=list)
    required_in: list[str] = Field(default_factory=list)
    cardinality: str = "1"
    default: str | None = None
    minimal: bool = False


class FacetCatalog:
    def __init__(self, facets: Mapping[str, FacetDeclaration]) -> None:
        self.facets = dict(facets)

    @classmethod
    def load(cls, path: Path) -> FacetCatalog:
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        declared = {
            name: FacetDeclaration.model_validate(spec or {}) for name, spec in (raw.get("facets") or {}).items()
        }
        return cls(declared)

    @classmethod
    def empty(cls) -> FacetCatalog:
        return cls({})

    def allowed_for(self, slot: TemplateSlot) -> list[str]:
        names = set(slot.facets.allowed)
        names.update(name for name, decl in self.facets.items() if slot.slot in decl.allowed_slots)
        return sorted(names)

    def required_for(self, slot: TemplateSlot) -> list[str]:
        names = set(slot.facets.required)
        names.update(name for name, decl in self.facets.items() if slot.slot in decl.required_in)
        return sorted(names)

    def is_minimal(self, name: str) -> bool:
        decl = self.facets.get(name)
        return decl.minimal if decl else False


_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_HIST_RE = re.compile(
    r"\b(Antike|Mittelalter|Jahrhundert|Jahrhunderts|entdeckte|erfand|erfunden|entwickelte|gegründet|begründete|"
    r"erstmals|damals|ursprünglich|früher|historisch|Geschichte)\b",
    re.IGNORECASE,
)
_FUTURE_RE = re.compile(
    r"\b(zukünftig|künftig|Zukunft|Prognose|prognostiziert|erwartet|voraussichtlich|geplant|Trend|Trends|"
    r"in den kommenden|werden könnte|soll .{0,40} werden)\b",
    re.IGNORECASE,
)
_VOLATILE_RE = re.compile(
    r"\b(derzeit|aktuell|zurzeit|momentan|Stand 20\d\d|Preis|Preise|Kosten|Stellen|Fachkräftemangel|Frist|"
    r"Fristen|Prozent|Umsatz|Marktanteil)\b",
    re.IGNORECASE,
)
_LEVEL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(Kita|Kindergarten|Elementarbereich|Vorschul)", re.IGNORECASE), "Elementar"),
    (re.compile(r"\b(Grundschule|Primarstufe|Sachunterricht)", re.IGNORECASE), "Primar"),
    (
        re.compile(
            r"\b(Sekundarstufe I|Sek I|Realschule|Hauptschule|Mittelstufe|Unterstufe|Oberschule)\b", re.IGNORECASE
        ),
        "Sek I",
    ),
    (re.compile(r"\b(Sekundarstufe II|Sek II|Oberstufe|Abitur|Gymnasiale)\b", re.IGNORECASE), "Sek II"),
    (
        re.compile(r"\b(Studium|Hochschule|Universität|Bachelor|Master|Studierende|Vorlesung)\b", re.IGNORECASE),
        "Hochschule",
    ),
    (
        re.compile(
            r"\b(Ausbildung|Berufsschule|Auszubildende|Lehrling|Berufsbildung|Gesellenprüfung|Meister)\b", re.IGNORECASE
        ),
        "Berufliche Bildung",
    ),
    (
        re.compile(r"\b(Weiterbildung|Fortbildung|Volkshochschule|Erwachsenenbildung)\b", re.IGNORECASE),
        "Erwachsenenbildung",
    ),
]
_ROLE_LEVELS = {
    "klexikon": ["Primar", "Sek I"],
    "wikiversity": ["Hochschule"],
    "wikibooks": ["Sek II", "Hochschule"],
}
_LEVEL_RULES_GELTUNG: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(EU|Europäische Union|EG-|EU-|Europäische Richtlinie|EN \d)", re.IGNORECASE), "EU"),
    (re.compile(r"\b(ISO|IEC|UN|WHO|international|weltweit)\b", re.IGNORECASE), "international"),
    (re.compile(r"\b(Bundes|Bundesgesetz|Grundgesetz|StGB|BGB|Verordnung des Bundes)", re.IGNORECASE), "Bund"),
    (re.compile(r"\b(Landes|Bundesland|Bundesländer|Kultusminister|Schulgesetz|Landesrecht)", re.IGNORECASE), "Land"),
    (
        re.compile(
            r"\b(Hausordnung|Dienstanweisung|Betriebsanweisung|Satzung|Richtlinie des Unternehmens)", re.IGNORECASE
        ),
        "Organisation",
    ),
]
_SUBJECT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(Sicherheit|Schutz|Unfall|Gefährdung)", re.IGNORECASE), "Sicherheit"),
    (re.compile(r"\b(Datenschutz|personenbezogen)", re.IGNORECASE), "Datenschutz"),
    (re.compile(r"\b(Zulassung|zugelassen|Genehmigung)", re.IGNORECASE), "Zulassung"),
    (re.compile(r"\b(Qualität|Norm|DIN|Standard)", re.IGNORECASE), "Qualität"),
    (re.compile(r"\b(Umwelt|Emission|Entsorgung)", re.IGNORECASE), "Umwelt"),
    (re.compile(r"\b(Arbeitsschutz|Arbeitssicherheit|Berufsgenossenschaft)", re.IGNORECASE), "Arbeitsschutz"),
    (re.compile(r"\b(Schul|Lehrplan|Bildungsstandard|Unterricht)", re.IGNORECASE), "Bildung"),
]
_CROSS_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(Nachhaltig|Klima|Umwelt|Ressourcen|Energie)", re.IGNORECASE), "Nachhaltigkeit"),
    (re.compile(r"\b(digital|Digitalisierung|Software|Computer|Internet|Daten)", re.IGNORECASE), "Digitalisierung"),
    (re.compile(r"\b(Demokratie|demokratisch|Partizipation|Wahl)", re.IGNORECASE), "Demokratiebildung"),
    (re.compile(r"\b(Gesundheit|Medizin|Krankheit|Therapie)", re.IGNORECASE), "Gesundheit"),
    (re.compile(r"\b(Medien|Medienkompetenz|Presse|Fernsehen)", re.IGNORECASE), "Medienbildung"),
    (re.compile(r"\b(Beruf|Berufsorientierung|Ausbildung|Arbeitsmarkt)", re.IGNORECASE), "Berufsorientierung"),
    (re.compile(r"\b(Inklusion|Barrierefreiheit|Behinderung)", re.IGNORECASE), "Inklusion"),
]


def _zeitbezug(chunks: Sequence[Chunk]) -> str:
    text = " ".join(f"{c.full_heading} {c.text}" for c in chunks)
    years = [int(y) for y in _YEAR_RE.findall(text)]
    now = datetime.now(UTC).year
    old_years = sum(1 for y in years if y < now - 30)
    hist_hits = len(_HIST_RE.findall(text))
    future_hits = len(_FUTURE_RE.findall(text))
    if future_hits >= 2 and future_hits >= hist_hits:
        return "prospektiv"
    if hist_hits + old_years >= 2:
        return "historisch"
    return "gegenwärtig"


def _bildungsstufe(chunks: Sequence[Chunk], sources: Mapping[str, Source]) -> list[str]:
    found: list[str] = []
    for chunk in chunks:
        source = sources.get(chunk.source_id)
        if source is not None:
            for level in _ROLE_LEVELS.get(source.project, []):
                if level not in found:
                    found.append(level)
        for pattern, level in _LEVEL_RULES:
            if pattern.search(chunk.text) and level not in found:
                found.append(level)
    return found


def _rule_values(chunks: Sequence[Chunk], rules: Sequence[tuple[re.Pattern[str], str]]) -> list[str]:
    text = " ".join(f"{c.full_heading} {c.text}" for c in chunks)
    return [value for pattern, value in rules if pattern.search(text)]


def annotate(
    slot: TemplateSlot,
    chunks: Sequence[Chunk],
    sources: Mapping[str, Source],
    catalog: FacetCatalog,
    level: str = "minimal",
    extractive: bool = True,
) -> dict[str, list[str]]:
    """Return facet values for a section; only facets allowed for the slot are produced."""
    allowed = set(catalog.allowed_for(slot))
    facets: dict[str, list[str]] = {}
    if not chunks:
        return facets

    def wanted(name: str) -> bool:
        return name in allowed and (level == "full" or catalog.is_minimal(name))

    if wanted("Zeitbezug"):
        facets["Zeitbezug"] = [_zeitbezug(chunks)]
    if wanted("Bildungsstufe"):
        levels = _bildungsstufe(chunks, sources)
        if levels:
            facets["Bildungsstufe"] = levels
    if wanted("Evidenzgrad"):
        values = ["belegt"] if extractive else ["Schlussfolgerung"]
        if facets.get("Zeitbezug") == ["prospektiv"]:
            values.append("Prognose")
        facets["Evidenzgrad"] = values
    if wanted("Haltbarkeit"):
        text = " ".join(c.text for c in chunks)
        facets["Haltbarkeit"] = ["volatil" if len(_VOLATILE_RE.findall(text)) >= 2 else "stabil"]
    if wanted("Geltungsebene"):
        values = _rule_values(chunks, _LEVEL_RULES_GELTUNG)
        if values:
            facets["Geltungsebene"] = values
    if wanted("Regelungsgegenstand"):
        values = _rule_values(chunks, _SUBJECT_RULES)
        if values:
            facets["Regelungsgegenstand"] = values
    if wanted("Querschnittsthema"):
        values = _rule_values(chunks, _CROSS_RULES)
        if values:
            facets["Querschnittsthema"] = values[:3]

    for name, default in slot.facets.defaults.items():
        if name in allowed and name not in facets and (level == "full" or catalog.is_minimal(name)):
            facets[name] = [default]
    return facets


def format_visible(facets: Mapping[str, Sequence[str]]) -> str:
    """Visible short form used only when FACETS_VISIBLE is enabled."""
    return " ".join(f"[{name}: {', '.join(values)}]" for name, values in facets.items() if values)


def format_marker(facets: Mapping[str, Sequence[str]]) -> str:
    return "; ".join(f"{name}={'|'.join(values)}" for name, values in facets.items() if values)


# Closes a facet block in parts 2 and 3 (``<!-- f: … -->`` … ``<!-- /f -->``), so blocks can be parsed out
END_MARKER = "<!-- /f -->"

_BILDUNGSSTUFE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"elementar|kita|vorschul", re.I), "Elementar"),
    (re.compile(r"primar|grundschul", re.I), "Primar"),
    (re.compile(r"sek(undar)?(bereich|stufe)?\s*(ii|2)\b|oberstufe", re.I), "Sek II"),
    (re.compile(r"sek(undar)?(bereich|stufe)?\s*(i|1)\b", re.I), "Sek I"),
    (re.compile(r"hochschul|universit", re.I), "Hochschule"),
    (re.compile(r"beruf", re.I), "Berufliche Bildung"),
    (re.compile(r"erwachsen|fortbildung|weiterbildung", re.I), "Erwachsenenbildung"),
)


def bildungsstufe_facet(label: str) -> str | None:
    """The facet value (config/facets.yaml) for a level as MEM, edu-sharing or OpenEduHub name it.

    The OpenEduHub vocabulary names a level three ways - prefLabel, altLabel and the concept URI
    (``.../educationalContext/sekundarstufe_1``). The labels read as they are; the URI does not,
    because its underscore is no whitespace, so the last path segment is unpacked first.
    """
    if "/" in label:
        label = label.rstrip("/").rsplit("/", 1)[-1]
    label = label.replace("_", " ")
    for pattern, value in _BILDUNGSSTUFE_RULES:
        if pattern.search(label):
            return value
    return None
