"""Question and answer pairs for a text or a topic (docs/umbau.md, U5).

Four stages, in the order of what they cost. ``rule-based`` builds the pairs from question templates over
the sentences of the text: the answer is the sentence itself, so nothing is invented and nothing is needed -
no model, no network. ``parse-based`` swaps the sentence subject for a question word using the spaCy parse
(app/synthesis/qa_parse.py), which yields four times as many sentences and an answer that is a noun phrase
rather than a whole sentence. ``models`` runs two small German models instead
(app/synthesis/qa_models.py): a generator writes the question for a noun phrase of the text, an extractive
model marks the place that answers it - the most accurate of the four and by far the slowest. ``llm`` lets
the b-api write them.

Without a method the profile picks one (D53): llm-free the parse, which is free and fast, every other profile the
LLM. parse-based and models fall back to the templates rather than failing, and so does llm while the b-api is not
available; llm without a configured LLM is a 503. The answer names the stage that actually produced the pairs, and
why the asked-for one did not.

This module is the endpoint itself: where the text comes from, which stage is asked, and what the answer
says. The wire contract lives in qa_schemas.py, the stages that can refuse in qa_stages.py.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.deps import get_service, node_errors
from app.api.limits import rate_limited
from app.api.v2.qa_schemas import LEVEL_PROPERTY, PROFILE_METHODS, Method, Pair, QaRequest, QaResponse
from app.api.v2.qa_stages import STAGES, LlmAllowance, levels_from, node_levels
from app.domain.models import Compendium, Resolution, SectionStatus
from app.domain.requests import GenerateRequest
from app.knowledge.recognise import load_spacy
from app.llm.deadline import Deadline
from app.service import CompendiumService, LlmNotConfiguredError, PartsUnavailableError, TopicNotFoundError
from app.sources.lehrplan.subjects import UnknownSubjectError
from app.synthesis.citations import without_markers
from app.synthesis.qa import QaPair, rule_based_pairs
from app.templates.manager import TemplateNotFoundError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["v2"])

NO_TAGGER_NOTE = (
    "spaCy-Modell nicht geladen; die Fragevorlagen können Satzanfänge nicht prüfen und fragen unter Umständen "
    "nach Adverbien statt nach Begriffen"
)


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


def _refuse_llm_without_one(request: Request, method: Method | None, profile: str, *, defaulted: bool) -> None:
    """The llm stage on a server without a configured LLM is a 503 (D53), as the LLM switches of a compendium are.

    Without the archives there is no service to ask; the stage then falls back and says so, as before.
    """
    service = request.app.state.service
    if method != "llm" or service is None:
        return
    try:
        service.refuse_without_llm(["method=llm"], profile, defaulted=defaulted)
    except LlmNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _part_one(service: CompendiumService, payload: QaRequest, allowance: LlmAllowance | None) -> Compendium:
    """Make part 1 of the compendium for the topic or node; its errors are the ones the compendium endpoint gives.

    Subject, preset and article choice go along, so the pairs come from the part 1 a compendium request with the same
    fields would make. With ``allowance`` part 1 spends from the budget and time of the whole request.

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
                    preset=payload.preset,
                    article_choice=payload.article_choice,
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


EXAMPLES = {
    "1 · regelbasiert": {
        "summary": "Fragevorlagen über die Sätze - braucht kein Modell und kein Netz",
        "description": (
            "Ein Thema erzeugt erst Teil 1 des Kompendiums und fragt dessen Bausteine ab. Die Stufe kennt "
            "vier Vorlagen; gemessen am 2026-09-21 greift auf einem Kompendiumtext nur jeder achte Satz, "
            "und die Hälfte der Fragen fragt nach einer Jahreszahl. Dafür kostet sie nichts. Ohne method wählt das "
            "Profil: llm-free nimmt parse-based, die übrigen llm."
        ),
        "value": {"topic": "Optik", "count": 20, "preset": "llm-free", "method": "rule-based"},
    },
    "2 · Satzsubjekte über den Parse": {
        "summary": "Das Satzsubjekt wird zum Fragewort - ohne Modell, aber viermal so ergiebig wie die Vorlagen",
        "description": (
            "Nutzt den spaCy-Parse, der ohnehin geladen ist: aus „Christiaan Huygens bemerkte um 1650, …“ "
            "wird „Wer bemerkte um 1650, …?“ mit „Christiaan Huygens“ als Antwort - die Antwort ist also eine "
            "Nominalphrase statt des ganzen Satzes. Gemessen am 2026-09-22 über 172 Sätze aus vier Kompendien: "
            "33 Sätze liefern eine Frage statt 8, rund 4 ms je Satz (warm), 26 der 33 Paare mangelfrei. Braucht das "
            "spaCy-Modell; ohne es fällt die Anfrage auf rule-based zurück und note sagt es."
        ),
        "value": {"topic": "Optik", "method": "parse-based", "count": 20},
    },
    "3 · kleine Modelle im Image": {
        "summary": "dehio/german-qg-t5-quad schreibt die Frage, gelectra-base-germanquad findet die Antwort",
        "description": (
            "Die Fragen entstehen aus den Nominalphrasen des Textes statt aus Vorlagen, darum sind sie "
            "vielfältiger: derselbe Text ergab 20 von 20 Paaren mit 18 verschiedenen Fragetypen und keiner "
            "einzigen Jahresfrage. Preis: rund 1,7 GB Arbeitsspeicher je Worker bei der ersten Anfrage und "
            "etwa 1,1 Sekunden je Paar auf CPU bei 20 Paaren - bei wenigen Paaren mehr, weil der "
            "Generator eine ganze Runde auf einmal erzeugt."
        ),
        "value": {"topic": "Optik", "method": "models", "count": 20, "max_answer_length": 240},
    },
    "4 · großes Sprachmodell über die b-api": {
        "summary": "Die b-api schreibt die Paare; als einzige Stufe kann sie Bildungsstufen zuordnen",
        "description": (
            "Braucht LLM_ENABLED und B_API_KEY - ohne sie fällt die Anfrage auf rule-based zurück und note "
            "sagt es. levels nimmt auch die Schreibweise des Vokabulars (Sekundarstufe I, Sekundarstufe 1 "
            "oder die Begriffs-URI). Wer das Kompendium schon hat, übergibt seinen Text und spart die "
            "Erzeugung."
        ),
        "value": {
            "topic": "Optik",
            "method": "llm",
            "count": 12,
            "levels": ["Sekundarstufe I", "Sekundarstufe II"],
        },
    },
    "5 · Thema aus einem Knoten": {
        "summary": "Paare zum Thema eines Knotens, hier die Sammlung Optik der WLO-Staging",
        "description": (
            "node_id und repository wie beim Kompendium: der Titel einer Sammlung wird zum Thema, bei einem "
            "Material der Artikel aus Titel und Beschreibung (D47); erst entsteht Teil 1 des Kompendiums, dann "
            "die Paare. repository ohne Angabe: das konfigurierte."
        ),
        "value": {
            "node_id": "9e7ae956-e9df-430f-bace-f3db4b910013",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
            "count": 8,
        },
    },
}


@router.post(
    "/qa",
    response_model=QaResponse,
    dependencies=[Depends(rate_limited)],
    summary="Frage-Antwort-Paare zu einem Text oder Thema",
)
def qa(payload: Annotated[QaRequest, Body(openapi_examples=EXAMPLES)], request: Request) -> QaResponse:
    """Build the pairs from the caller's text, or from the compendium this endpoint makes for the topic.

    Both steps in one call, or one step with a text of your own: that is the pipeline. A topic makes
    part 1 first and asks about its blocks - not about the raw articles, which carry far more than the
    compendium ever shows.
    """
    if payload.levels:
        # From here on only the project's own values travel, so the prompt and the pairs speak one
        # vocabulary and _level() can map the model's answer back onto it.
        payload = payload.model_copy(update={"levels": levels_from(request, payload.levels)})
    profile = payload.preset or request.app.state.settings.preset_default
    if payload.method is None:
        payload = payload.model_copy(update={"method": PROFILE_METHODS[profile]})
    _refuse_llm_without_one(request, payload.method, profile, defaulted=not payload.preset)
    topic: str | None = None
    resolution: Resolution | None = None
    node = None
    allowance = _allowance(request, payload)
    if payload.topic or payload.node_id:
        service = get_service(request)  # a topic needs the archives; a plain text does not
        compendium = _part_one(service, payload, allowance)
        topic, resolution, node = compendium.topic, compendium.resolution, compendium.node
        text = _text_of_compendium(compendium)
    else:
        text = payload.text or ""
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
            log.info("QA fell back to the templates: %s", reason)
            notes.append(reason)
        else:
            method = payload.method
    if pairs is None:
        nlp = load_spacy(request.app.state.settings.spacy_model)
        if nlp is None:
            notes.append(NO_TAGGER_NOTE)
        pairs = rule_based_pairs(text, limit=payload.count, max_answer_length=payload.max_answer_length, nlp=nlp)
    if payload.levels and method != "llm":
        # The effective stage decides, not the one that was asked for: an llm that fell back loses the
        # levels with it, and that has to be said, not left for the reader to infer from empty fields.
        notes.append(
            f"Stufen ({LEVEL_PROPERTY}) kann nur die Stufe llm zuordnen; {method} liefert die Paare ohne Stufe"
        )
    return QaResponse(
        method=method,
        topic=topic,
        resolution=resolution,
        node=node,
        chars=len(text),
        pairs=[
            Pair(question=pair.question, answer=pair.answer, level=pair.level_value) for pair in pairs[: payload.count]
        ],
        note="; ".join(notes) or None,
    )
