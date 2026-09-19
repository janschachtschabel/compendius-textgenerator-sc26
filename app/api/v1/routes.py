"""Legacy endpoints (PLAN.md 8.1): the request shape of the old service on the new orchestrator.

Unlike the old service, a failure is a status code and never a compendium that contains an error text: the
topic that no archive knows is 404, a repository that does not answer 502, a part this service is not set up
for 503. What the request asked for and what the new service does with it stays visible in ``statistics.notes``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_service
from app.api.limits import rate_limited
from app.api.v1 import adapter
from app.api.v1.models import (
    CompendiumRequest,
    CompendiumResponse,
    InputType,
    PipelineCompendiumOnlyRequest,
    PipelineCompendiumOnlyResponse,
    PipelineRequest,
    PipelineResponse,
    PipelineStatistics,
    QAPair,
    QAResponse,
)
from app.api.v1.qa import pairs_for
from app.domain.models import Compendium
from app.domain.requests import GenerateRequest
from app.matching.registry import UnknownMatcherError
from app.observability.metrics import record_compendium
from app.service import CompendiumService, PartsUnavailableError, TopicNotFoundError
from app.sources.wlo.client import CollectionNotFoundError, EduSharingError
from app.templates.manager import TemplateNotFoundError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["v1"])


def _generate(service: CompendiumService, payload: GenerateRequest) -> Compendium:
    """Run the orchestrator and map its failures to the status codes of 8.1."""
    try:
        compendium = service.generate(payload)
    except TopicNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": "Thema in den Archiven nicht gefunden", "resolution": exc.resolution.model_dump()},
        ) from exc
    except CollectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EduSharingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Template nicht gefunden: {exc.args[0]}") from exc
    except UnknownMatcherError as exc:
        raise HTTPException(status_code=422, detail=f"Unbekannte Matching-Strategie: {exc}") from exc
    except PartsUnavailableError as exc:
        log.warning("compendium request refused: %s", exc)
        raise HTTPException(status_code=503, detail=f"Kein angefragter Teil ist erzeugbar: {exc}") from exc
    record_compendium(compendium)
    return compendium


def _build(text: str | None, config: Any, notes: list[str]) -> GenerateRequest:
    try:
        return adapter.build_request(text, config, notes)
    except adapter.UnsupportedOptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:  # a request the new model rejects, e.g. neither topic nor collection
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/compendium", response_model=CompendiumResponse, dependencies=[Depends(rate_limited)])
def compendium(payload: CompendiumRequest, request: Request) -> CompendiumResponse:
    """Compendium for a topic (``input_type=text``) or for the output of a linker run."""
    notes: list[str] = []
    if payload.input_type is InputType.TEXT:
        if not (payload.text or "").strip():
            raise HTTPException(status_code=400, detail="text required for input_type=text")
        topic, extra = payload.text or "", {"input_length": len(payload.text or "")}
    else:
        if not payload.linker_data:
            raise HTTPException(status_code=400, detail="linker_data required for input_type=linker_output")
        topic, entities = adapter.topic_of_linker_data(payload.linker_data)
        extra = {"entities_count": entities}
        if not topic:
            raise HTTPException(status_code=400, detail="linker_data enthält weder original_text noch Entitäten")
    generated = _generate(get_service(request), _build(topic, payload.config, notes))
    return adapter.compendium_response(generated, input_type=payload.input_type.value, notes=notes, **extra)


@router.post(
    "/pipeline-compendium-only",
    response_model=PipelineCompendiumOnlyResponse,
    dependencies=[Depends(rate_limited)],
)
def pipeline_compendium_only(
    payload: PipelineCompendiumOnlyRequest, request: Request
) -> PipelineCompendiumOnlyResponse:
    """Topic resolution and compendium in one call; ``linker_output`` names the articles the text is built from."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    notes: list[str] = []
    try:
        adapter.note_linker_config(payload.config.linker, notes)
    except adapter.UnsupportedOptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    started = time.perf_counter()
    generated = _generate(get_service(request), _build(text, payload.config.compendium, notes))
    total = time.perf_counter() - started
    timings = generated.audit.timings_ms
    resolve = sum(timings.get(phase, 0) for phase in ("resolve", "corpus", "segment")) / 1000
    return PipelineCompendiumOnlyResponse(
        original_text=text,
        linker_output=adapter.linker_output(generated, text),
        compendium_output=adapter.compendium_response(
            generated, input_type="text", notes=notes, input_length=len(text)
        ),
        pipeline_statistics=PipelineStatistics(
            processing_times={"linker": round(resolve, 3), "compendium": round(max(total - resolve, 0.0), 3)},
            completed_steps=2,
            total_steps=2,
            errors=[],
            total_processing_time=round(total, 3),
        ),
    )


@router.post("/pipeline", response_model=PipelineResponse, dependencies=[Depends(rate_limited)])
def pipeline(payload: PipelineRequest, request: Request) -> PipelineResponse:
    """The three steps of the old pipeline in one answer: articles, compendium, question and answer pairs."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    notes: list[str] = []
    try:
        adapter.note_linker_config(payload.config.linker, notes)
    except adapter.UnsupportedOptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    service = get_service(request)
    started = time.perf_counter()
    generated = _generate(service, _build(text, payload.config.compendium, notes))
    written = time.perf_counter()
    settings = payload.config.qa
    pairs = pairs_for(
        service,
        text=generated.markdown,  # the pairs are about the compendium, as in the old service
        count=settings.num_pairs,
        max_answer_length=settings.max_answer_length,
        level_property=settings.level_property,
        level_values=settings.level_values or (),
    )
    done = time.perf_counter()
    timings = generated.audit.timings_ms
    resolve = sum(timings.get(phase, 0) for phase in ("resolve", "corpus", "segment")) / 1000
    return PipelineResponse(
        original_text=text,
        linker_output=adapter.linker_output(generated, text),
        compendium_output=adapter.compendium_response(
            generated, input_type="text", notes=notes, input_length=len(text)
        ),
        qa_output=QAResponse(original_text=generated.markdown, qa=[QAPair(**vars(pair)) for pair in pairs]),
        pipeline_statistics=PipelineStatistics(
            processing_times={
                "linker": round(resolve, 3),
                "compendium": round(max(written - started - resolve, 0.0), 3),
                "qa": round(done - written, 3),
            },
            completed_steps=3,
            total_steps=3,
            errors=[],
            total_processing_time=round(done - started, 3),
        ),
    )
