"""Entity kind of a source from its lead: person, organisation, project, network or a single work.

Shared by the actors block (which lists them) and the matching policy (which keeps their body
text out of the default block: a composer or a film about the topic is not the topic).
"""

from __future__ import annotations

import re

from app.domain.models import Source

_PERSON_RE = re.compile(
    r"\(\*\s*(?:\d{1,2}\.\s*)?(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|"
    r"Dezember)?\s*\d{3,4}|\(\*\s*\d{3,4}|\bwar eine?\b.{0,80}\b(Physiker|Physikerin|Chemiker|Chemikerin|"
    r"Mathematiker|Mathematikerin|Optiker|Optikerin|Astronom|Astronomin|Ingenieur|Ingenieurin|Wissenschaftler|"
    r"Wissenschaftlerin|Forscher|Forscherin|Erfinder|Erfinderin|Unternehmer|Unternehmerin|Politiker|Politikerin|"
    r"Philosoph|Philosophin|Gelehrter|Gelehrte|Arzt|Ärztin|Mediziner|Medizinerin|Biologe|Biologin|Komponist|"
    r"Komponistin|Schriftsteller|Schriftstellerin|Pädagoge|Pädagogin|Lehrer|Lehrerin|Informatiker|Informatikerin)\b"
)
_ORG_RE = re.compile(
    r"\b(Unternehmen|Gesellschaft|Verein|Verband|Institut|Universität|Hochschule|Behörde|Stiftung|Organisation|"
    r"Akademie|Konzern|Hersteller|Firma|Aktiengesellschaft|Ministerium|Bundesamt|Bundesanstalt|Fachgesellschaft|"
    r"Berufsverband|Kammer|Genossenschaft|Forschungseinrichtung|Forschungszentrum|Museum|Bibliothek)\b"
)
_PROJECT_RE = re.compile(r"\b(Projekt|Programm|Initiative|Förderprogramm|Kampagne|Mission|Vorhaben)\b")
_NETWORK_RE = re.compile(r"\b(Netzwerk|Verbund|Community|Allianz|Konsortium|Zusammenschluss|Bündnis|Kooperation)\b")
_WORK_RE = re.compile(
    r"\b(ist|war) (ein|eine|der|die|das) [^.]{0,120}?\b(Film|Spielfilm|Fernsehfilm|Dokumentarfilm|Roman|Novelle|"
    r"Erzählung|Gedicht|Drama|Oper|Operette|Musical|Sinfonie|Symphonie|Programmsinfonie|Kantate|Sonate|Konzert|"
    r"Album|Lied|Single|Gemälde|Skulptur|Fernsehserie|Serie|Computerspiel|Videospiel|Comic|Manga|Sachbuch|Werk)\b"
)
_COPULA_RE = re.compile(r"\b(ist|war)\b")


def classify_entity(source: Source) -> str | None:
    """Cascade: Person, Organisation, Vorhaben, Netzwerk; first match wins; ``None`` for a subject."""
    lead = source.lead_text[:600]
    if not lead:
        return None
    if _PERSON_RE.search(lead):
        return "Person"
    head = lead[:260]
    if _COPULA_RE.search(head):
        if _ORG_RE.search(head):
            return "Organisation"
        if _PROJECT_RE.search(head):
            return "Vorhaben"
        if _NETWORK_RE.search(head):
            return "Netzwerk"
    return None


def is_work(source: Source) -> bool:
    """A single work (film, novel, symphony, album, …) named as such in the first sentence of the lead."""
    return bool(_WORK_RE.search(source.lead_text[:300]))


def is_subject(source: Source) -> bool:
    """Neither an actor nor a single work: the article is about a subject or a sub-area."""
    return classify_entity(source) is None and not is_work(source)
