"""Legacy QA (PLAN.md 8.1, D14): the LLM writes the pairs, question templates stand in when it cannot.

The old endpoint needed the LLM and answered 500 or 503 without it. Here a text always yields pairs: with a
configured and available LLM the model writes them (and spreads them over the levels a caller asked for),
otherwise they come from the sentences of the text through question templates, where an answer is a sentence of
the text and nothing is invented. Levels are only distributed by the model; the templates echo the property.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_service
from app.api.limits import rate_limited
from app.api.v1.models import QAPair, QARequest, QAResponse
from app.llm.deadline import Deadline
from app.service import CompendiumService
from app.synthesis.qa import QaPair, rule_based_pairs

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.post("/qa", response_model=QAResponse, dependencies=[Depends(rate_limited)])
def qa(payload: QARequest, request: Request) -> QAResponse:
    """Question and answer pairs for a text; without an LLM they come from the templates."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    pairs = pairs_for(
        get_service(request),
        text=text,
        count=payload.num_pairs,
        max_answer_length=payload.max_answer_length,
        level_property=payload.level_property,
        level_values=payload.level_values or (),
    )
    return QAResponse(original_text=payload.text, qa=[QAPair(**vars(pair)) for pair in pairs])


def pairs_for(
    service: CompendiumService,
    *,
    text: str,
    count: int,
    max_answer_length: int,
    level_property: str | None = None,
    level_values: Sequence[str] = (),
) -> list[QaPair]:
    """Pairs for a text: from the LLM when it can deliver, otherwise from the question templates."""
    request = QARequest(
        text=text,
        num_pairs=count,
        max_answer_length=max_answer_length,
        level_property=level_property,
        level_values=list(level_values) or None,
    )
    pairs = _from_llm(service, request, text)
    if pairs is not None:
        return pairs
    return rule_based_pairs(text, limit=count, max_answer_length=max_answer_length, level_property=level_property)


def _from_llm(service: CompendiumService, payload: QARequest, text: str) -> list[QaPair] | None:
    """The model's pairs, or ``None`` when the LLM is unusable, fails or answers nothing parsable."""
    llm = service.llm
    if llm is None or service.llm_unavailable() is not None:
        return None
    try:
        return llm.qa.pairs(
            text,
            count=payload.num_pairs,
            max_answer_length=payload.max_answer_length,
            budget=llm.open_budget(),
            level_property=payload.level_property,
            level_values=payload.level_values or (),
            deadline=Deadline(service.settings.request_timeout_s),
        )
    except Exception:  # the LLM layer must never break an answer the templates can give
        log.exception("QA pairs from the LLM failed unexpectedly")
        return None
