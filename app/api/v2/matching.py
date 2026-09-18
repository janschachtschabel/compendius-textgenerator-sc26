"""Matching endpoints: available strategies and the comparator (PLAN.md 4.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_service
from app.matching.eval_runner import DEFAULT_MATCHERS, compare_topic, find_gold
from app.matching.registry import list_strategies
from app.service import TopicNotFoundError

router = APIRouter(prefix="/api/v2/matching", tags=["matching"])


class CompareRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=300)
    matchers: list[str] = Field(default_factory=lambda: list(DEFAULT_MATCHERS), min_length=1, max_length=8)
    template_id: str | None = None
    target_length: int = Field(12_000, ge=2_000, le=60_000)


@router.get("/strategies")
def matching_strategies() -> list[dict[str, Any]]:
    return list_strategies()


@router.post("/compare")
def compare(payload: CompareRequest, request: Request) -> dict[str, Any]:
    """Run several strategies on one topic; with a gold file the metrics come along, agreement always."""
    service = get_service(request)
    known = {strategy["id"] for strategy in list_strategies()}
    unknown = [name for name in payload.matchers if name not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unbekannte Strategie(n): {', '.join(unknown)}")
    gold_dir = request.app.state.settings.eval_gold_dir
    try:
        result = compare_topic(
            service,
            payload.topic,
            payload.matchers,
            gold_for=lambda *names: find_gold(gold_dir, *names),
            template_id=payload.template_id,
            target_length=payload.target_length,
        )
    except TopicNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": "Thema in den Archiven nicht gefunden", "resolution": exc.resolution.model_dump()},
        ) from exc
    gold: dict[str, Any] | None = None
    if result.gold is not None and result.alignment is not None:
        gold = {
            "topic": result.gold.topic,
            "labeled": len(result.alignment.gold_by_chunk),
            "stale": len(result.alignment.stale),
            "labeled_by": result.gold.labeled_by,
        }
    return {
        "topic": result.topic,
        "resolution": result.resolution.model_dump(),
        "chunks": result.chunks,
        "gold": gold,
        "results": {
            name: {
                "assigned": outcome.assigned,
                "filled_slots": outcome.filled_slots,
                "duration_ms": outcome.duration_ms,
                "metrics": outcome.metrics.model_dump() if outcome.metrics is not None else None,
            }
            for name, outcome in result.results.items()
        },
        "agreement": result.agreement,
    }
