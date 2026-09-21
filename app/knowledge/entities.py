"""Entity kind of a source from its lead: person, organisation, project, network or a single work.

Shared by the actors block (which lists them) and the matching policy (which keeps their body
text out of the default block: a composer or a film about the topic is not the topic).
"""

from __future__ import annotations

import re

from app.domain.models import Source

_MONTHS = "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
# A German biography opens with the birth and death markers. The marker can stand behind an alias
# ("… auch bekannt als Tycho de Brahe; * 14. Dezember 1546"), and the date behind it can carry the
# Julian/Gregorian suffix ("* 14. Dezemberjul. / 24. Dezember 1645greg."), so what is read is the
# marker plus the first token of the date, not a whole date.
_BORN_DIED_RE = re.compile(r"[*†]\s*(?:\d{1,2}\.|(?:" + _MONTHS + r")\b|\d{3,4}\b)")
_PROFESSION_RE = re.compile(
    r"\bwar eine?\b.{0,80}\b(Physiker|Physikerin|Chemiker|Chemikerin|"
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
_KINDS = (("Organisation", _ORG_RE), ("Vorhaben", _PROJECT_RE), ("Netzwerk", _NETWORK_RE))
# German names an organisation after what it is, so the type word in the name is the signal. Behind the
# copula it only counts inside the defining sentence.
_IS_A = r"\b(?:ist|war) (?:ein|eine|einer|der|die|das) [^.]{0,120}?"
_DEFINED_AS = {kind: re.compile(_IS_A + pattern.pattern) for kind, pattern in _KINDS}


def classify_entity(source: Source) -> str | None:
    """Cascade: Person, Organisation, Vorhaben, Netzwerk; first match wins; ``None`` for a subject.

    Nothing here is read wherever it likes. The birth and death markers count in the **name** before the
    copula, and so does a type word; behind the copula a type word counts only within the defining
    sentence, so a second sentence listing companies does not turn a concept into an organisation. And an
    article whose title *is* the type word is that concept, never an instance of it.

    Measured against the real Wikipedia on 2026-09-21. Type words, over 29 hand-labelled articles: 20
    right before, 26 after - six false actors gone (the concepts behind economy, company, museum,
    library, enterprise and cooperation) and no real actor lost. The markers, over 1500 random articles:
    71 persons won and 47 lost, and 45 of those 47 are lists of names ("X ist der Familienname folgender
    Personen"), which the old rule counted as one person because the entries carry birth dates. The 71
    are the leads the old rule could not read: an alias before the marker, or a Julian/Gregorian date.
    Of 18 historical persons it missed eight, one of them labelled an organisation once the person rule
    had failed.

    What stays wrong is a lead whose type word belongs to a *different* entity - a phone "vom Hersteller
    Samsung", a stipend "der Stiftung"; that needs the head of the predicate, not a pattern. A wrong kind
    is worse than a missing one here, because the matching policy keeps the body text of actors out of
    the default block.
    """
    if any(pattern.fullmatch(source.title.strip()) for _, pattern in _KINDS):
        return None
    lead = source.lead_text[:600]
    if not lead:
        return None
    # The markers count in the name, not wherever they like: a museum names its founder's death
    # date in a later sentence, and a list of names puts the copula first ("X ist der Familienname
    # folgender Personen"). The profession is read in the whole lead, where it stands.
    lead_copula = _COPULA_RE.search(lead)
    name_part = lead[: lead_copula.start()] if lead_copula else lead
    if _BORN_DIED_RE.search(name_part) or _PROFESSION_RE.search(lead):
        return "Person"
    head = lead[:260]
    copula = _COPULA_RE.search(head)
    name = head[: copula.start()] if copula else ""
    for kind, pattern in _KINDS:
        if pattern.search(name) or _DEFINED_AS[kind].search(head):
            return kind
    return None


def is_work(source: Source) -> bool:
    """A single work (film, novel, symphony, album, …) named as such in the first sentence of the lead."""
    return bool(_WORK_RE.search(source.lead_text[:300]))


def is_subject(source: Source) -> bool:
    """Neither an actor nor a single work: the article is about a subject or a sub-area."""
    return classify_entity(source) is None and not is_work(source)
