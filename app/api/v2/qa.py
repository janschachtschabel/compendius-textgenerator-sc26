"""Question and answer pairs for a text, a topic or a node (docs/umbau.md, U5; D55).

Four stages, in the order of what they cost. ``rule-based`` asks from the spaCy parse of each sentence - Wann,
Wo, Wer, Was, Worauf, Wie viele, Warum, definitions - and from the glossary and actors of a compendium
(app/synthesis/qa_rules.py); the answer is the sentence itself, so nothing is invented, and without the spaCy
model it falls back to four templates. ``parse-based`` only swaps the sentence subject for a question word
(app/synthesis/qa_parse.py). ``models`` runs two small German models (app/synthesis/qa_models.py): a generator
writes the question for a noun phrase of the text, an extractive model marks the place that answers it - varied
and by far the slowest of the free stages. ``llm`` lets the b-api write them.

A topic or a node is asked about through part 1 of its compendium, and that part 1 is always made without an LLM
(D55, Jan): fast, free, and the same knowledge whatever stage asks about it. Without a method the profile picks
one: llm-free the rules, balanced the small models, the profiles that pay for an LLM anyway the LLM. parse-based
and models fall back to the rules rather than failing, and so does llm while the b-api is not available; llm
without a configured LLM is a 503. The answer names the stage that actually produced the pairs, why the asked-for
one did not, and how many pairs came when the text held fewer than were asked for.

This module is the endpoint itself: where the text comes from, which stage is asked, and what the answer
says. The wire contract lives in qa_schemas.py, the stages that can refuse in qa_stages.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.deps import get_service, node_errors
from app.api.limits import rate_limited
from app.api.v2.qa_schemas import LEVEL_PROPERTY, PROFILE_METHODS, Method, Pair, QaRequest, QaResponse
from app.api.v2.qa_stages import STAGES, LlmAllowance, levels_from, node_levels
from app.domain.models import Compendium, Resolution, SectionStatus
from app.domain.requests import PRESETS, ArticleChoice, GenerateRequest
from app.knowledge.recognise import load_spacy
from app.llm.deadline import Deadline
from app.service import CompendiumService, LlmNotConfiguredError, PartsUnavailableError, TopicNotFoundError
from app.sources.lehrplan.subjects import UnknownSubjectError
from app.synthesis.citations import without_markers
from app.synthesis.qa import QaPair, rule_based_pairs
from app.synthesis.qa_rules import rule_pairs
from app.templates.manager import TemplateNotFoundError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["v2"])

NO_TAGGER_NOTE = (
    "spaCy-Modell nicht geladen; die Regeln fallen auf vier Fragevorlagen zurück, die Satzanfänge nicht prüfen "
    "können und unter Umständen nach Adverbien statt nach Begriffen fragen"
)
KNOWLEDGE_PROFILE = "llm-free"  # part 1 of a topic or node, whatever profile picks the stage (D55)
FREE_STAGES = frozenset({"rule-based", "parse-based"})


@dataclass(frozen=True)
class Knowledge:
    """What the pairs are asked about: the prose, and for a compendium its glossary and actors and its topic."""

    text: str
    glossary: str = ""
    actors: str = ""
    topic: str | None = None


def _allowance(request: Request, payload: QaRequest) -> LlmAllowance | None:
    """One token budget and one deadline for the whole request when the llm stage is asked for.

    Part 1 used to open its own and the pairs another after it (review of 2026-09-25), so a request could spend
    twice LLM_MAX_TOKENS_PER_REQUEST and twice REQUEST_TIMEOUT_S. Without a configured LLM there is nothing to share.
    """
    service = request.app.state.service
    llm = service.llm if service is not None else None
    if payload.method != "llm" or llm is None:
        return None
    return LlmAllowance(llm.open_budget(), Deadline(service.settings.request_timeout_s))


def _refuse_llm_without_one(request: Request, needed: list[str], profile: str, *, defaulted: bool) -> None:
    """What needs an LLM on a server without one is a 503 (D53), as the LLM switches of a compendium are.

    Without the archives there is no service to ask; the stage then falls back and says so, as before.
    """
    service = request.app.state.service
    if not needed or service is None:
        return
    try:
        service.refuse_without_llm(needed, profile, defaulted=defaulted)
    except LlmNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _article_choice(payload: QaRequest, profile: str) -> ArticleChoice | None:
    """Who chooses the article of part 1: the request if it says, else the rules - except for a node (D55).

    Jan wanted the knowledge of a topic made without an LLM. The article of a material node is another matter:
    the rules find it in about half of the cases, the LLM in nearly all (D47, M23), so there the profile decides
    as it does for a compendium.
    """
    if payload.article_choice is not None:
        return payload.article_choice
    if not payload.node_id:
        return None
    return "llm" if PRESETS[profile]["article_choice"] == "llm" else "rule-based"


def _part_one(
    service: CompendiumService, payload: QaRequest, allowance: LlmAllowance | None, article_choice: ArticleChoice | None
) -> Compendium:
    """Make part 1 of the compendium for the topic or node; its errors are the ones the compendium endpoint gives.

    Part 1 is made with the switches of llm-free whatever the profile (D55, Jan): the profile picks the stage that
    asks, not the knowledge it asks about, and an LLM that chose paragraphs or wrote blocks would cost seconds and
    tokens the pairs do not show. Only ``article_choice`` may still call on the LLM (``_article_choice``); the
    subject goes along as in a compendium request, and with ``allowance`` part 1 spends from the budget and time of
    the whole request.

    Only ``world`` is asked for: part 2 lists curriculum elements and part 3 lists materials of a
    collection, and neither is prose a question can be built from.
    """
    try:
        with node_errors():  # no collection here, so a 404 of the repository can only be the node's
            return service.generate(
                GenerateRequest(
                    topic=payload.topic,
                    node_id=payload.node_id,
                    repository=payload.repository,
                    subject=payload.subject,
                    preset=KNOWLEDGE_PROFILE,
                    article_choice=article_choice,
                    parts=["world"],
                ),
                deadline=allowance.deadline if allowance is not None else None,
                budget=allowance.budget if allowance is not None else None,
            )
    except TopicNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail()) from exc
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc
    except PartsUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Teil 1 ist nicht erzeugbar: {exc}") from exc
    except LlmNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnknownSubjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _text_of_compendium(compendium: Compendium) -> str:
    """The prose of the content blocks, in reading order - not the apparatus around them.

    Two things are left out, and both for the same reason: they are apparatus, not subject matter.
    The markdown of the finished document carries headings, citation numbers and facet markers, so
    only the block texts are read. And of those the generated blocks are skipped - the sources block,
    the glossary and the actor directory are link lists and tables that a question generator turns
    into nonsense.

    Measured against the running service on 2026-09-21 for one topic: of 27 614 characters of blocks,
    20 522 were the three generated ones. Asked about, they produced a question about the year 1999
    answered with a literature line and its ISBN - three quarters of the text taught nothing, and the
    literature lines are where the flood of year questions came from.
    """
    joined = "\n\n".join(
        section.text.strip()
        for section in compendium.sections
        if section.text.strip() and section.status is not SectionStatus.GENERATED
    )
    return without_markers(joined)


def _knowledge(compendium: Compendium) -> Knowledge:
    """The prose of part 1, and the two generated blocks the rules can read on their own terms (D55).

    The glossary holds one definition per related article and the actor list the first sentence of each person's
    article: no prose a parse could ask about, but a definition asks "Was ist …?" and a person "Wer war …?".
    """
    blocks = {section.slot_key: section.text for section in compendium.sections if section.text.strip()}
    title = compendium.resolution.title if compendium.resolution is not None else compendium.topic
    return Knowledge(
        text=_text_of_compendium(compendium),
        glossary=blocks.get("glossar", ""),
        actors=blocks.get("akteure", ""),
        topic=title,
    )


def _rule_stage(request: Request, knowledge: Knowledge, payload: QaRequest) -> tuple[list[QaPair], str | None]:
    """The pairs of the rules, and a note when the spaCy model they read is missing.

    Without the model only the four templates of the old stage are left (app/synthesis/qa.py).
    """
    nlp = load_spacy(request.app.state.settings.spacy_model)
    if nlp is None:
        pairs = rule_based_pairs(knowledge.text, limit=payload.count, max_answer_length=payload.max_answer_length)
        return pairs, NO_TAGGER_NOTE
    pairs = rule_pairs(
        knowledge.text,
        nlp=nlp,
        count=payload.count,
        max_answer_length=payload.max_answer_length,
        topic=knowledge.topic,
        glossary=knowledge.glossary,
        actors=knowledge.actors,
    )
    return pairs, None


def _shortfall(delivered: int, asked: int, method: str) -> str | None:
    """What the answer says when the text held fewer pairs than were asked for (Jan, 2026-09-25)."""
    if delivered >= asked:
        return None
    more = "; die Modelle (models) und das LLM (llm) fragen freier" if method in FREE_STAGES else ""
    return f"{delivered} statt {asked} Paare: mehr Fragen gibt der Text für {method} nicht her{more}"


EXAMPLES = {
    "1 · Thema, Profil llm-free": {
        "summary": "Regeln über den spaCy-Parse: vielseitige Fragen ohne Modell und ohne LLM",
        "description": (
            "Ein Thema erzeugt erst Teil 1 des Kompendiums, immer ohne LLM (D55), und fragt dessen Bausteine, sein "
            "Glossar und seine Akteure ab: Wann, Wo, Wer, Was, Worauf, Wie viele, Warum und Definitionen, die Arten "
            "abwechselnd, die Antwort ist der ganze Satz. Hält der Text weniger Fragen, als count verlangt, sagt note, "
            "wie viele es sind. Auf sechs Themen mit je 20 verlangten Paaren lieferten die Regeln 96 Paare in 0,3 s "
            "je Text, die Hälfte nach zwei Gutachtern mangelfrei (M30)."
        ),
        "value": {"topic": "Albert Einstein", "count": 20, "preset": "llm-free"},
    },
    "2 · Thema, Standardprofil balanced": {
        "summary": "Die zwei kleinen Modelle im Image - vielseitig, langsamer, ohne LLM",
        "description": (
            "dehio/german-qg-t5-quad schreibt die Frage, gelectra-base-germanquad markiert die Antwort im Text, "
            "darum sind die Antworten kurze Textstellen. Rund 1 s je Paar und 1,3 GB Arbeitsspeicher je Worker ab "
            "der ersten Anfrage. Ohne preset gilt PRESET_DEFAULT, ausgeliefert balanced; Teil 1 entsteht auch hier "
            "ohne LLM. Auf sechs Themen kamen immer so viele Paare wie verlangt, nach zwei Gutachtern aber nur 25 "
            "von 120 mangelfrei (M30): Antworten, die nicht passen, Sachfehler und unklare Fragen."
        ),
        "value": {"topic": "Optik", "count": 10},
    },
    "3 · Thema, Profil best-quality": {
        "summary": "Die b-api schreibt die Paare; als einzige Stufe kann sie Bildungsstufen zuordnen",
        "description": (
            "Braucht LLM_ENABLED und B_API_KEY, sonst antwortet der Dienst mit 503. levels nimmt auch die "
            "Schreibweise des Vokabulars (Sekundarstufe I, Sekundarstufe 1 oder die Begriffs-URI). Teil 1 und die "
            "Paare teilen sich ein Token-Budget und eine Frist. Auf sechs Themen 99 von 120 Paaren mangelfrei, rund "
            "2.400 Tokens je Text (M30)."
        ),
        "value": {
            "topic": "Optik",
            "preset": "best-quality",
            "count": 12,
            "levels": ["Sekundarstufe I", "Sekundarstufe II"],
        },
    },
    "4 · eigener Text": {
        "summary": "Paare zu einem Text, den Sie schon haben - es entsteht kein Kompendium",
        "description": (
            "Etwa das Markdown eines Kompendiums, das Sie schon abgerufen haben. preset wählt auch hier das "
            "Verfahren; subject und article_choice gelten nur mit topic oder node_id."
        ),
        "value": {
            "text": (
                "Die Optik ist ein Teilgebiet der Physik. Isaac Newton zerlegte 1666 weißes Licht mit einem Prisma. "
                "Eine Sammellinse dient der Bündelung von Lichtstrahlen. Linsen brechen das Licht, weil es sich in "
                "Glas langsamer ausbreitet als in Luft."
            ),
            "preset": "llm-free",
            "count": 5,
        },
    },
    "5 · Thema aus einem Knoten": {
        "summary": "Paare zum Thema eines Knotens, hier die Sammlung Optik der WLO-Staging",
        "description": (
            "node_id und repository wie beim Kompendium: der Titel einer Sammlung wird zum Thema, bei einem "
            "Material der Artikel aus Titel und Beschreibung (D47). Den Artikel eines Materials wählt in den Profilen "
            "mit LLM das LLM, weil die Regeln ihn nur in etwa jedem zweiten Fall finden; sonst entsteht Teil 1 ohne "
            "LLM. repository ohne Angabe: das konfigurierte."
        ),
        "value": {
            "node_id": "9e7ae956-e9df-430f-bace-f3db4b910013",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
            "preset": "llm-free",
            "count": 8,
        },
    },
    "6 · einzelnes Verfahren: parse-based": {
        "summary": "Nur das Satzsubjekt wird zum Fragewort; die Antwort ist das Subjekt",
        "description": (
            "Ein einzeln gesetztes method geht dem Profil vor. parse-based war bis D55 das Verfahren von llm-free: "
            "schnell, aber es fragt nur nach Satzsubjekten und liefert oft weniger Paare als verlangt (44 statt 120 "
            "auf sechs Themen, M30)."
        ),
        "value": {"topic": "Optik", "method": "parse-based", "count": 10},
    },
}


@router.post(
    "/qa",
    response_model=QaResponse,
    dependencies=[Depends(rate_limited)],
    summary="Frage-Antwort-Paare zu einem Text oder Thema",
)
def qa(payload: Annotated[QaRequest, Body(openapi_examples=EXAMPLES)], request: Request) -> QaResponse:
    """Build the pairs from the caller's text, or from the compendium this endpoint makes for the topic or node.

    Both steps in one call, or one step with a text of your own: that is the pipeline. A topic makes
    part 1 first, without an LLM, and asks about its blocks - not about the raw articles, which carry far
    more than the compendium ever shows.
    """
    if payload.levels:
        # From here on only the project's own values travel, so the prompt and the pairs speak one
        # vocabulary and _level() can map the model's answer back onto it.
        payload = payload.model_copy(update={"levels": levels_from(request, payload.levels)})
    profile = payload.preset or request.app.state.settings.preset_default
    if payload.method is None:
        payload = payload.model_copy(update={"method": PROFILE_METHODS[profile]})
    article_choice = _article_choice(payload, profile) if payload.topic or payload.node_id else None
    needed = [
        f"{name}=llm"
        for name, value in (("method", payload.method), ("article_choice", article_choice))
        if value == "llm"
    ]
    _refuse_llm_without_one(request, needed, profile, defaulted=not payload.preset)
    topic: str | None = None
    resolution: Resolution | None = None
    node = None
    allowance = _allowance(request, payload)
    if payload.topic or payload.node_id:
        service = get_service(request)  # a topic needs the archives; a plain text does not
        compendium = _part_one(service, payload, allowance, article_choice)
        topic, resolution, node = compendium.topic, compendium.resolution, compendium.node
        knowledge = _knowledge(compendium)
    else:
        knowledge = Knowledge(text=payload.text or "")
    text = knowledge.text
    if not text.strip():
        raise HTTPException(status_code=404, detail="Zum Thema stehen in den Archiven keine Texte bereit.")

    method: Method = "rule-based"
    notes: list[str] = []
    if node is not None and payload.method == "llm" and not payload.levels:
        # Only the llm stage assigns levels; the others would only report the node's levels as lost (D47)
        inherited = node_levels(request, node.educational_contexts)
        if inherited:
            payload = payload.model_copy(update={"levels": inherited})
            notes.append(f"Stufen aus dem Knoten: {', '.join(inherited)}")
    pairs: list[QaPair] | None = None
    if payload.method in STAGES:
        pairs, reason = STAGES[payload.method](request, text, payload, node, allowance)
        if pairs is None:
            log.info("QA fell back to the rules: %s", reason)
            notes.append(reason)
        else:
            method = payload.method
    if pairs is None:
        pairs, missing = _rule_stage(request, knowledge, payload)
        if missing:
            notes.append(missing)
    if payload.levels and method != "llm":
        # The effective stage decides, not the one that was asked for: an llm that fell back loses the
        # levels with it, and that has to be said, not left for the reader to infer from empty fields.
        notes.append(
            f"Stufen ({LEVEL_PROPERTY}) kann nur die Stufe llm zuordnen; {method} liefert die Paare ohne Stufe"
        )
    pairs = pairs[: payload.count]
    shortfall = _shortfall(len(pairs), payload.count, method)
    if shortfall:
        notes.append(shortfall)
    return QaResponse(
        method=method,
        topic=topic,
        resolution=resolution,
        node=node,
        chars=len(text),
        pairs=[Pair(question=pair.question, answer=pair.answer, level=pair.level_value) for pair in pairs],
        note="; ".join(notes) or None,
    )
