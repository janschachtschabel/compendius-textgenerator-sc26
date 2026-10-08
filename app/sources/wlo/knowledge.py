"""Knowledge collection (PLAN.md 6.3): the materials of a collection become sources for part 1.

Every material counts, whatever its licence (Jan, 2026-10-01, D70: the service is built for editorial teams with
content of their own). By default a material brings what its metadata says, its description; with ``fulltext`` its
extracted text as well, cached for a week, fetched a few at a time. A failing material never fails the compendium:
it is listed in the result so the audit can say what is missing.
"""

from __future__ import annotations

import logging
import re
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from app.concurrency import map_in_threads
from app.domain.models import ArticleSection, Paragraph, Source, SourceRole
from app.domain.spelling import readable
from app.prose import split_sentences
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
# A longer line of a material text becomes several paragraphs: about the 97th percentile of the archive paragraphs
# matching and writing are measured on (median 622, p95 1,678, p99 2,417 characters over 1,944 chunks of nine topics,
# 2026-10-03). An extracted text may come as one line of any length (audit 2026-10-02, A07).
PARAGRAPH_MAX_CHARS = 2_000
TIME_UP = "Zeitbudget der Anfrage erschöpft"  # compared by identity in material_sources
# Consent dialogs and cookie notices crawled from the material's page are not knowledge, a text about cookies is: a
# notice has the site use the cookies ("Wir nutzen Cookies", "Diese Website verwendet Cookies") or talks like a dialog
# ("Ihre Auswahl", "um Ihnen"), or it uses a dialog's words. Every line naming "cookie" or "consent" went before,
# "Cookies sind kleine Textdateien …" with it, while the consent dialog that stood in 51 of 151 material texts passed:
# it names no cookie (audit 2026-10-03, F08; M68). A lesson's "wir" or "Ihre Schülerinnen" alone makes no notice.
# the wording of consent dialogs alone; words a lesson about the browser uses too ("Cookie-Einstellungen",
# "Datenschutzeinstellungen") are no sign (review of F08)
_CONSENT_PHRASES = (
    "store and/or access information",
    "manage consent",
    "von diesem anbieter erhobenen daten",
    "der anbieter kann ip-adressen",
)
# the German wording of the same purpose of the TCF dialogs: "Informationen auf einem Gerät speichern und/oder abrufen"
_DEVICE_ACCESS = re.compile(
    r"informationen auf einem (?:end)?gerät[^.!?]{0,40}?und/oder"
    r"|und/oder[^.!?]{0,60}?informationen auf einem (?:end)?gerät",
    re.IGNORECASE,
)
# the name of a dialog's settings counts with its polite address ("Datenschutzeinstellungen: Hier können Sie …"),
# not in a lesson about the browser's ("Öffne die Cookie-Einstellungen deines Browsers")
_SETTINGS = re.compile(
    r"datenschutzeinstellungen|privatsphäre-einstellungen|cookie-?einstellungen|cookie-richtlinie"
    r"|cookie (?:settings|policy)",
    re.IGNORECASE,
)
_SITE = r"(?:wir|we|(?:diese|unsere)[nrs]? (?:web)?(?:seite|site)|this (?:web)?site)"  # Webseite, Website, Seite
_SITE_USES_COOKIES = re.compile(
    rf"\b{_SITE}\b[^.!?]{{0,40}}?\b(?:nutz|verwend|setz|einsetz|benutz|use|using)\w*[^.!?]{{0,60}}?\bcookie"
    rf"|\b{_SITE}\b[^.!?]{{0,40}}?\bcookies\b[^.!?]{{0,40}}?\b(?:verwendet|genutzt|gesetzt|eingesetzt|benutzt|used)\b"
    # The verb before its subject (M74): "Daher verwendet diese Website Cookies"; "wir" only with the place of the
    # site, "Derzeit verwenden wir auf unserer Website keine Cookies" - a lesson says "nutzen wir die Entwicklertools
    # des Browsers, um die Cookies … anzusehen" (review of 2026-10-08)
    rf"|\b(?:nutz|verwend|setz|benutz)\w*\s+(?:diese|unsere)[nrs]? (?:web)?(?:seite|site)\b[^.!?]{{0,60}}?\bcookie"
    rf"|\b(?:nutz|verwend|setz|benutz)\w*\s+(?:wir|we)\b[^.!?]{{0,40}}?\b(?:auf|on) "
    rf"(?:unsere[rm]?|diese[rm]?|our|this) (?:web)?(?:seite|site)\b[^.!?]{{0,60}}?\bcookie",
    re.IGNORECASE,
)
# the polite form of a dialog, so case matters: "Ihre Auswahl", not "Ihre Schülerinnen" or "Ihre Aufgabe"
_READER_DIALOG = re.compile(r"\b(?:Ihre (?:Einwilligung|Zustimmung|Auswahl|Einstellungen|Privatsphäre)|um Ihnen)\b")
# a request to agree in the polite form ("Klicken Sie auf „Alle akzeptieren“, um … Cookies zuzustimmen"), within one
# sentence; "Sie" opening a sentence is the plural ("Sie werden gespeichert …"), so it needs a word before it
_AGREE = re.compile(
    r"\b(?:akzeptier|zustimm|zuzustimm|einverstanden|ablehn|zulass|zuzulass|accept|agree)\w*", re.IGNORECASE
)
_POLITE = re.compile(r"(?<=\S )(?:Sie|Ihnen|Ihre[mnrs]?)\b")


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
    as the archives write theirs (app/domain/spelling.py).

    A line longer than ``PARAGRAPH_MAX_CHARS`` becomes several paragraphs at its sentence ends, and ``max_chars``
    bounds them all, the first one too: the paragraph that would cross it keeps the whole sentences that fit, and the
    text ends there. Before, the first line stayed whole, 220,001 characters against a cap of 500 (audit 2026-10-02,
    A07).
    """
    paragraphs: list[str] = []
    room = max_chars
    for raw in text.splitlines():
        line = readable(" ".join(raw.split()))
        if len(line) < MIN_PARAGRAPH_CHARS:
            continue
        if len(line) <= PARAGRAPH_MAX_CHARS and is_consent_notice(line):  # a notice of its own line goes whole
            continue
        if len(line) > PARAGRAPH_MAX_CHARS:  # a text of one line (A07) loses the sentences of a notice, no more;
            head = line[: 2 * room + PARAGRAPH_MAX_CHARS]  # read only what may still be kept
            line = " ".join(sentence for sentence in split_sentences(head) if not is_consent_notice(sentence))
        for piece in _pieces(line, PARAGRAPH_MAX_CHARS):
            if len(piece) > room:
                head = _pieces(piece, room)[0] if room >= MIN_PARAGRAPH_CHARS else ""
                if len(head) >= MIN_PARAGRAPH_CHARS:
                    paragraphs.append(head)
                return paragraphs
            if len(piece) >= MIN_PARAGRAPH_CHARS:  # the end of a sentence cut at its spaces may be short
                paragraphs.append(piece)
                room -= len(piece)
    return paragraphs


def is_consent_notice(text: str) -> bool:
    """Whether ``text`` comes from a consent dialog or a cookie notice, not from a text about cookies (see
    ``_CONSENT_PHRASES``)."""
    lower = text.lower()
    if any(phrase in lower for phrase in _CONSENT_PHRASES) or _DEVICE_ACCESS.search(text):
        return True
    if _SETTINGS.search(text) and _POLITE.search(text):
        return True
    if "cookie" not in lower:
        return False
    if _SITE_USES_COOKIES.search(text) or _READER_DIALOG.search(text):
        return True
    return any(
        "cookie" in sentence.lower() and _AGREE.search(sentence) and _POLITE.search(sentence)
        for sentence in split_sentences(text)
    )


def _pieces(line: str, limit: int) -> list[str]:
    """``line`` in pieces of at most ``limit`` characters, cut at its sentence ends; a sentence longer than that, text
    without any end such as an extracted table, at its spaces."""
    if len(line) <= limit:
        return [line]
    pieces: list[str] = []
    current = ""
    for sentence in split_sentences(line):
        for part in textwrap.wrap(sentence, limit) if len(sentence) > limit else [sentence]:
            if current and len(current) + 1 + len(part) > limit:
                pieces.append(current)
                current = part
            else:
                current = f"{current} {part}" if current else part
    if current:
        pieces.append(current)
    return pieces


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
    errors: Counter[str] = Counter()
    for ref, text, error in outcomes:
        if error is TIME_UP:
            result.timed_out += 1
            continue
        if error is not None:
            log.debug("material %s (%s) could not be read: %s", ref.id, ref.title, error)
            errors[error] += 1
            result.failed.append(ref.id)
            continue
        paragraphs = paragraphs_from_text(text or "", options.max_chars)
        if not paragraphs and len(ref.description) < MIN_PARAGRAPH_CHARS:
            result.empty += 1
            continue
        result.sources.append(_source(ref, paragraphs))
    if errors:
        # One line per request, a WARNING only when no text came: a text the repository refuses is refused with every
        # request, and two warnings per material buried the ones that mattered (logging review of 2026-10-08)
        level = logging.WARNING if len(result.failed) == len(chosen) else logging.INFO
        common = ", ".join(f"{count}x {error}" for error, count in errors.most_common(3))
        log.log(level, "%d of %d material texts not readable: %s", len(result.failed), len(chosen), common)
    return result
