"""Question and answer pairs for a text or a topic (docs/umbau.md, U5).

Two stages today. ``rule-based`` builds the pairs from question templates over the sentences of the text: the
answer is the sentence itself, so nothing is invented and nothing is needed - no model, no network. ``llm``
lets the b-api write them and falls back to the templates rather than failing; the answer names the stage that
actually produced the pairs, and why the other one did not.

``models`` runs two small German models instead (app/synthesis/qa_models.py): a generator writes the question
for a noun phrase of the text, an extractive model marks the place that answers it. Both are baked into the
image; without them, or without the spaCy model their candidates come from, this stage falls back as well.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_service
from app.api.limits import rate_limited
from app.domain.models import Compendium, Resolution
from app.domain.requests import GenerateRequest
from app.knowledge.recognise import load_spacy
from app.llm.deadline import Deadline
from app.service import CompendiumService, PartsUnavailableError, TopicNotFoundError
from app.synthesis.facets import bildungsstufe_facet
from app.synthesis.qa import QaPair, rule_based_pairs
from app.synthesis.qa_models import answer_candidates, load_qa_models, model_pairs
from app.templates.manager import TemplateNotFoundError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["v2"])

Method = Literal["rule-based", "models", "llm"]
LEVEL_PROPERTY = "Bildungsstufe"  # the one level vocabulary the project owns (config/facets.yaml)
MAX_TEXT_CHARS = 50_000  # bounds the request body and the text a topic yields; both end up in the same code
NO_TAGGER_NOTE = (
    "spaCy-Modell nicht geladen; die Fragevorlagen können Satzanfänge nicht prüfen und fragen unter Umständen "
    "nach Adverbien statt nach Begriffen"
)


class QaRequest(BaseModel):
    text: str | None = Field(
        None,
        min_length=1,
        max_length=MAX_TEXT_CHARS,
        description="The text the pairs are made from - the markdown of a compendium you already "
        "have, or any other text",
    )
    topic: str | None = Field(
        None,
        min_length=1,
        max_length=300,
        description="Instead of a text: part 1 of the compendium for this topic is made first and the "
        "pairs are asked about it. That costs a compendium generation - hand the text over instead when "
        "you already have one",
    )
    method: Method = Field(
        "rule-based",
        description="rule-based needs nothing and is the default; models uses the two German models baked "
        "into the image (question generator plus extractive answers); llm lets the b-api write the pairs. "
        "Both fall back to rule-based when they cannot run, and note says why",
    )
    count: int = Field(5, ge=1, le=50, description="Upper bound of the pairs")
    max_answer_length: int = Field(300, ge=50, le=2000, description="Characters per answer; longer ones are cut")
    levels: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Educational levels to spread the pairs over. Optional; without them nothing changes. "
        "Written as the Bildungsstufe vocabulary writes it - the label (Sekundarstufe I), an alternative label "
        "(Sekundarstufe 1) or the concept URI - or as config/facets.yaml writes it (Elementar, Primar, Sek I, "
        "Sek II, Hochschule, Berufliche Bildung, Erwachsenenbildung). Only the llm stage can assign one; the "
        "other stages return the pairs without a level and say so in note",
    )

    @model_validator(mode="after")
    def _text_or_topic(self) -> QaRequest:
        if not self.text and not self.topic:
            raise ValueError("text oder topic ist erforderlich")
        return self


class Pair(BaseModel):
    question: str
    answer: str
    level: str | None = Field(None, description=f"The {LEVEL_PROPERTY} the llm stage assigned, if any")


class QaResponse(BaseModel):
    method: Method = Field(description="The stage that produced the pairs; llm falls back to rule-based")
    topic: str | None = Field(None, description="The resolved topic, when one was asked for")
    resolution: Resolution | None = None
    chars: int = Field(description="Characters of the text the pairs were made from")
    pairs: list[Pair]
    note: str | None = Field(
        None,
        description="What a reader should know about how the pairs came about: why the LLM did not write them, "
        "or that the spaCy model for checking the question subjects is missing",
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
    """The prose of the blocks, in reading order - not the markdown around them.

    The finished document carries headings, citation numbers, facet markers and a sources block. A
    question generated from those asks about a number or a heading, so only the block texts are used.
    """
    return "\n\n".join(section.text.strip() for section in compendium.sections if section.text.strip())


def _from_models(request: Request, text: str, payload: QaRequest) -> tuple[list[QaPair] | None, str]:
    """The pairs of the two small models, or ``None`` and the reason the templates have to do it."""
    settings = request.app.state.settings
    models = load_qa_models(settings.qg_model_path, settings.qa_model_path)
    if models is None:
        return None, "QA-Modelle nicht im Image (QG_MODEL_PATH/QA_MODEL_PATH); Regelmodus verwendet"
    nlp = load_spacy(settings.spacy_model)
    if nlp is None:
        return None, "spaCy-Modell fehlt; ohne seine Nominalphrasen gibt es keine Antwortkandidaten"
    # Both the model and the splitter have to see the same string, so the offsets line up
    prepared = " ".join(text[:MAX_TEXT_CHARS].split())
    candidates = answer_candidates(nlp(prepared), prepared)
    pairs = model_pairs(candidates, models, count=payload.count, max_answer_length=payload.max_answer_length)
    if not pairs:
        return None, "Die Modelle fanden keine beantwortbare Frage; Regelmodus verwendet"
    return pairs, ""


def _from_llm(request: Request, text: str, payload: QaRequest) -> tuple[list[QaPair] | None, str]:
    """The model's pairs, or ``None`` and the reason the templates have to do it."""
    service = request.app.state.service
    llm = service.llm if service is not None else None
    if llm is None:
        return None, "LLM nicht konfiguriert (LLM_ENABLED/B_API_KEY); Regelmodus verwendet"
    unavailable = service.llm_unavailable()
    if unavailable:
        return None, f"LLM nicht verfügbar: {unavailable}; Regelmodus verwendet"
    pairs = llm.qa.pairs(
        text,
        count=payload.count,
        max_answer_length=payload.max_answer_length,
        budget=llm.open_budget(),
        level_property=LEVEL_PROPERTY if payload.levels else None,
        level_values=payload.levels,
        deadline=Deadline(service.settings.request_timeout_s),
    )
    if pairs is None:
        return None, "LLM lieferte keine verwertbaren Paare; Regelmodus verwendet"
    return pairs, ""


def _levels_from(request: Request, levels: Sequence[str]) -> list[str]:
    """Map what the caller sent onto the project's own level values, or refuse it by name.

    The Bildungsstufe vocabulary (OpenEduHub) names a level as prefLabel ("Sekundarstufe I"), altLabel
    ("Sekundarstufe 1") or concept URI (".../educationalContext/sekundarstufe_1"); ``bildungsstufe_facet``
    reads all three, and the project's own values map to themselves. Four levels of that vocabulary -
    Schule, Förderschule, Fernunterricht, Informelles Lernen - have no counterpart in config/facets.yaml.
    They are refused by name rather than bent onto a neighbour, because a made-up level would travel on
    the pairs into a service that does not know it.
    """
    service = request.app.state.service
    declaration = service.facets.facets.get(LEVEL_PROPERTY) if service is not None else None
    if declaration is None or not declaration.values:
        raise HTTPException(
            status_code=422,
            detail=f"Stufenvokabular {LEVEL_PROPERTY} ist nicht konfiguriert (config/facets.yaml)",
        )
    mapped: list[str] = []
    unknown: list[str] = []
    for level in levels:
        value = bildungsstufe_facet(level)
        if value is not None and value in declaration.values:
            mapped.append(value)
        else:
            unknown.append(level)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unbekannte Stufen: {', '.join(unknown)}. "
                f"Erlaubt sind {', '.join(declaration.values)} sowie ihre Bezeichnungen und URIs "
                f"aus dem Vokabular {LEVEL_PROPERTY}"
            ),
        )
    return list(dict.fromkeys(mapped))


EXAMPLES = {
    "kuerzeste Anfrage": {
        "summary": "Ein Thema: das Kompendium wird erzeugt und abgefragt",
        "value": {"topic": "Optik", "count": 5},
    },
    "mit den Schaltern": {
        "summary": "Eigener Text, die Modellstufe und Bildungsstufen",
        "description": (
            "Wer das Kompendium schon hat, übergibt seinen Text und spart die Erzeugung. method wählt die "
            "Stufe; levels wirkt nur mit llm und nimmt auch die Schreibweise des Vokabulars "
            "(Sekundarstufe I, Sekundarstufe 1, oder die Begriffs-URI)."
        ),
        "value": {
            "text": "Die Optik ist ein Teilgebiet der Physik und handelt vom Licht.",
            "method": "llm",
            "count": 8,
            "max_answer_length": 240,
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
        payload = payload.model_copy(update={"levels": _levels_from(request, payload.levels)})
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
        produce = _from_llm if payload.method == "llm" else _from_models
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
