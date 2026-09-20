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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.deps import corpus_for_topic, get_service
from app.api.limits import rate_limited
from app.domain.models import Resolution, Source
from app.knowledge.recognise import load_spacy
from app.llm.deadline import Deadline
from app.synthesis.qa import QaPair, rule_based_pairs
from app.synthesis.qa_models import answer_candidates, load_qa_models, model_pairs

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2", tags=["v2"])

Method = Literal["rule-based", "models", "llm"]
MAX_TEXT_CHARS = 50_000  # bounds the request body and the text a topic yields; both end up in the same code
NO_TAGGER_NOTE = (
    "spaCy-Modell nicht geladen; die Fragevorlagen können Satzanfänge nicht prüfen und fragen unter Umständen "
    "nach Adverbien statt nach Begriffen"
)


class QaRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"topic": "Optik", "count": 5}]})

    text: str | None = Field(None, min_length=1, max_length=MAX_TEXT_CHARS, description="The text to ask about")
    topic: str | None = Field(
        None, min_length=1, max_length=300, description="Instead of a text: the articles of this topic are used"
    )
    method: Method = Field(
        "rule-based",
        description="rule-based needs nothing and is the default; models uses the two German models baked "
        "into the image (question generator plus extractive answers); llm lets the b-api write the pairs. "
        "Both fall back to rule-based when they cannot run, and note says why",
    )
    count: int = Field(5, ge=1, le=50, description="Upper bound of the pairs")
    max_answer_length: int = Field(300, ge=50, le=2000, description="Characters per answer; longer ones are cut")

    @model_validator(mode="after")
    def _text_or_topic(self) -> QaRequest:
        if not self.text and not self.topic:
            raise ValueError("text oder topic ist erforderlich")
        return self


class Pair(BaseModel):
    question: str
    answer: str


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


def _text_of(sources: list[Source]) -> str:
    """The articles as one text, bounded: whole sections in reading order, cut at a section border."""
    parts: list[str] = []
    total = 0
    for source in sources:
        for section in source.sections:
            text = "\n\n".join(paragraph.text for paragraph in section.paragraphs).strip()
            if not text or total + len(text) > MAX_TEXT_CHARS:
                continue
            parts.append(text)
            total += len(text)
    return "\n\n".join(parts)


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
        deadline=Deadline(service.settings.request_timeout_s),
    )
    if pairs is None:
        return None, "LLM lieferte keine verwertbaren Paare; Regelmodus verwendet"
    return pairs, ""


@router.post(
    "/qa",
    response_model=QaResponse,
    dependencies=[Depends(rate_limited)],
    summary="Frage-Antwort-Paare zu einem Text oder Thema",
)
def qa(payload: QaRequest, request: Request) -> QaResponse:
    """Build the pairs, from the caller's text or from the articles of a topic."""
    topic: str | None = None
    resolution: Resolution | None = None
    if payload.topic:
        service = get_service(request)  # a topic needs the archives; a plain text does not
        topic, resolution, sources = corpus_for_topic(service, service.registry, payload.topic)
        text = _text_of(sources)
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
    return QaResponse(
        method=method,
        topic=topic,
        resolution=resolution,
        chars=len(text),
        pairs=[Pair(question=pair.question, answer=pair.answer) for pair in pairs[: payload.count]],
        note="; ".join(notes) or None,
    )
