"""Question and answer pairs for a text or a topic (docs/umbau.md, U5).

Two stages today. ``rule-based`` builds the pairs from question templates over the sentences of the text: the
answer is the sentence itself, so nothing is invented and nothing is needed - no model, no network. ``llm``
lets the b-api write them and falls back to the templates rather than failing; the answer names the stage that
actually produced the pairs, and why the other one did not.

``models`` runs two small German models instead (app/synthesis/qa_models.py): a generator writes the question
for a noun phrase of the text, an extractive model marks the place that answers it. Both are baked into the
image; without them, or without the spaCy model their candidates come from, this stage falls back as well.

This module is the endpoint itself: where the text comes from, which stage is asked, and what the answer
says. The wire contract lives in qa_schemas.py, the two optional stages in qa_stages.py.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.api.deps import get_service
from app.api.limits import rate_limited
from app.api.v2.qa_schemas import LEVEL_PROPERTY, Method, Pair, QaRequest, QaResponse
from app.api.v2.qa_stages import from_llm, from_models, levels_from
from app.domain.models import Compendium, Resolution, SectionStatus
from app.domain.requests import GenerateRequest
from app.knowledge.recognise import load_spacy
from app.service import CompendiumService, PartsUnavailableError, TopicNotFoundError
from app.synthesis.citations import without_markers
from app.synthesis.qa import QaPair, rule_based_pairs
from app.templates.manager import TemplateNotFoundError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["v2"])

NO_TAGGER_NOTE = (
    "spaCy-Modell nicht geladen; die Fragevorlagen können Satzanfänge nicht prüfen und fragen unter Umständen "
    "nach Adverbien statt nach Begriffen"
)


def _part_one(service: CompendiumService, topic: str) -> Compendium:
    """Make part 1 of the compendium for the topic; its errors are the ones the compendium endpoint gives.

    Only ``world`` is asked for: part 2 lists curriculum elements and part 3 lists materials of a
    collection, and neither is prose a question can be built from.
    """
    try:
        return service.generate(GenerateRequest(topic=topic, parts=["world"]))
    except TopicNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": "Thema in den Archiven nicht gefunden", "resolution": exc.resolution.model_dump()},
        ) from exc
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc
    except PartsUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Teil 1 ist nicht erzeugbar: {exc}") from exc


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
    "1 · regelbasiert (Standard)": {
        "summary": "Fragevorlagen über die Sätze - braucht kein Modell und kein Netz",
        "description": (
            "Ein Thema erzeugt erst Teil 1 des Kompendiums und fragt dessen Bausteine ab. Die Stufe kennt "
            "vier Vorlagen; gemessen am 2026-09-21 greift auf einem Kompendiumtext nur jeder achte Satz, "
            "und die Hälfte der Fragen fragt nach einer Jahreszahl. Dafür kostet sie nichts."
        ),
        "value": {"topic": "Optik", "count": 20},
    },
    "2 · kleine Modelle im Image": {
        "summary": "dehio/german-qg-t5-quad schreibt die Frage, gelectra-base-germanquad findet die Antwort",
        "description": (
            "Die Fragen entstehen aus den Nominalphrasen des Textes statt aus Vorlagen, darum sind sie "
            "vielfältiger: derselbe Text ergab 20 von 20 Paaren mit 18 verschiedenen Fragetypen und keiner "
            "einzigen Jahresfrage. Preis: rund 1,7 GB Arbeitsspeicher je Worker bei der ersten Anfrage und "
            "etwa 2,2 Sekunden je Paar auf CPU."
        ),
        "value": {"topic": "Optik", "method": "models", "count": 20, "max_answer_length": 240},
    },
    "3 · großes Sprachmodell über die b-api": {
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
    topic: str | None = None
    resolution: Resolution | None = None
    if payload.topic:
        service = get_service(request)  # a topic needs the archives; a plain text does not
        compendium = _part_one(service, payload.topic)
        topic, resolution = compendium.topic, compendium.resolution
        text = _text_of_compendium(compendium)
    else:
        text = payload.text or ""
    if not text.strip():
        raise HTTPException(status_code=404, detail="Zum Thema stehen in den Archiven keine Texte bereit.")

    method: Method = "rule-based"
    notes: list[str] = []
    pairs: list[QaPair] | None = None
    if payload.method in ("llm", "models"):
        produce = from_llm if payload.method == "llm" else from_models
        pairs, reason = produce(request, text, payload)
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
        chars=len(text),
        pairs=[
            Pair(question=pair.question, answer=pair.answer, level=pair.level_value) for pair in pairs[: payload.count]
        ],
        note="; ".join(notes) or None,
    )
